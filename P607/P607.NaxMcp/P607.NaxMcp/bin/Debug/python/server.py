"""Local MCP Streamable HTTP server, compatible with Python 3.8.

Run: python server.py --config config.json --port 8000
Crestron: crestron_main(module_info), started by P607.cs (SimplSharpPythonInterface.Run)
"""

import argparse
import asyncio
import ipaddress
import json
import logging
import math
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import threading

from helpers import cbridge  # also puts python/ and python/lib on sys.path
from aiohttp import web

from crestron.config import DEFAULT_CONFIG
from protocol import PROTOCOL_VERSION, TOOL_DEFINITIONS
from runtime import Runtime, Session, STOP, rpc_error


def is_loopback(host):
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _authority(value):
    try:
        parsed = urlsplit("http://" + value)
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or not is_loopback(parsed.hostname)
        ):
            return None
        return parsed.hostname.lower(), parsed.port or 80
    except (ValueError, AttributeError):
        return None


@web.middleware
async def local_only(request, handler):
    # Loopback peers only, and Host/Origin must name this loopback server: a web
    # page that rebinds its own DNS name to 127.0.0.1 cannot reach the tools.
    if request.app.get("allow_remote"):
        # Remote mode, no authentication: any host on the network may connect.
        # Browser requests (they carry Origin) are still refused.
        if request.headers.get("Origin") is not None:
            raise web.HTTPForbidden(text="Browser requests are not supported")
        response = await handler(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    authority = _authority(request.headers.get("Host", ""))
    sock = request.transport.get_extra_info("sockname") if request.transport else None
    if authority is None or (sock and authority[1] != sock[1]):
        raise web.HTTPForbidden(text="Invalid Host header")
    peer = request.transport.get_extra_info("peername") if request.transport else None
    if peer and not is_loopback(peer[0]):
        raise web.HTTPForbidden(text="Only loopback clients are supported")
    origin = request.headers.get("Origin")
    if origin is not None:
        try:
            parsed = urlsplit(origin)
            valid = (
                parsed.scheme == request.scheme
                and parsed.username is None
                and parsed.password is None
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
                and _authority(parsed.netloc) == authority
            )
        except ValueError:
            valid = False
        if not valid:
            raise web.HTTPForbidden(text="Invalid Origin header")
    response = await handler(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _accepts(request, media):
    for entry in request.headers.get("Accept", "").split(","):
        parts = [part.strip().lower() for part in entry.split(";")]
        if parts[0] == media:
            if any(
                part.startswith("q=")
                and part[2:].strip() in ("0", "0.0", "0.00", "0.000")
                for part in parts[1:]
            ):
                continue
            return True
    return False


def _version(request, required=True):
    version = request.headers.get("MCP-Protocol-Version")
    if version != PROTOCOL_VERSION and (required or version is not None):
        raise web.HTTPBadRequest(text="Unsupported or missing MCP-Protocol-Version")


def _session(request):
    runtime = request.app["mcp_runtime"]
    identifier = request.headers.get("Mcp-Session-Id")
    if not identifier:
        raise web.HTTPBadRequest(text="Mcp-Session-Id is required")
    session = runtime.sessions.get(identifier)
    if session is None or session.closed:
        raise web.HTTPNotFound(text="Unknown or expired MCP session")
    session.touch()
    return session


def _valid_message(message):
    # Not left to dispatch: notifications never reach it, and Session.start reads
    # params and keys on id first; invalid messages also get HTTP 400 here.
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return False
    if not isinstance(message.get("method"), str):
        return False
    if "params" in message and not isinstance(message["params"], dict):
        return False
    if "id" in message:
        value = message["id"]
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (str, int, float))
            or isinstance(value, float)
            and not math.isfinite(value)
        ):
            return False
    return True


async def post(request):
    runtime = request.app["mcp_runtime"]
    if runtime.stopping:
        raise web.HTTPServiceUnavailable(text="Server is shutting down")
    if not _accepts(request, "application/json") or not _accepts(
        request, "text/event-stream"
    ):
        raise web.HTTPNotAcceptable(
            text="Accept must include application/json and text/event-stream"
        )
    if request.content_type != "application/json":
        raise web.HTTPUnsupportedMediaType(text="Content-Type must be application/json")
    try:
        message = await request.json()
    except ValueError:
        return web.json_response(rpc_error(None, -32700, "Parse error"), status=400)
    if not _valid_message(message):
        return web.json_response(rpc_error(None, -32600, "Invalid Request"), status=400)
    method = message["method"]
    if method == "initialize":
        _version(request, required=False)
        if "id" not in message:
            return web.json_response(
                rpc_error(None, -32600, "initialize must be a request"), status=400
            )
        if request.headers.get("Mcp-Session-Id"):
            raise web.HTTPBadRequest(text="Initialize must create a new session")
        if len(runtime.sessions) >= runtime.max_sessions:
            raise web.HTTPServiceUnavailable(
                text="MCP session limit reached", headers={"Retry-After": "5"}
            )
        session = Session(runtime)
        response = await session.service.dispatch(message)
        if "error" in response:
            return web.json_response(response, status=400)
        runtime.sessions[session.id] = session
        return web.json_response(response, headers={"Mcp-Session-Id": session.id})

    _version(request)
    session = _session(request)
    if "id" not in message:
        if method == "notifications/cancelled":
            params = message.get("params", {})
            value = params.get("requestId")
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                session.cancel(value)
        # Notifications bypass device dispatch so cancellation stays responsive.
        return web.Response(status=202)
    if len(session.requests) >= runtime.max_inflight:
        raise web.HTTPTooManyRequests(
            text="Session request limit reached", headers={"Retry-After": "1"}
        )
    try:
        task = session.start(message)
    except ValueError:
        return web.json_response(
            rpc_error(message["id"], -32600, "Request id is already in flight"),
            status=400,
        )
    # A dropped HTTP connection must not cancel a device change midway. Only
    # notifications/cancelled or closing the session cancels, never once it writes
    # (final server teardown after the cleanup deadline is the one exception).
    response = await asyncio.shield(task)
    return web.json_response(response)


async def get(request):
    if not _accepts(request, "text/event-stream"):
        raise web.HTTPNotAcceptable(text="Accept must include text/event-stream")
    _version(request)
    session = _session(request)
    if request.headers.get("Last-Event-ID"):
        raise web.HTTPBadRequest(text="This server does not offer event replay")
    if session.stream is not None:
        raise web.HTTPConflict(text="A notification stream is already open")
    queue = asyncio.Queue(maxsize=session.runtime.max_queue)
    session.stream = queue
    response = web.StreamResponse(
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        }
    )
    try:
        await response.prepare(request)
        await response.write(b": connected\n\n")
        while not session.closed:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                await response.write(b": keepalive\n\n")
                continue
            if event is STOP:
                break
            payload = json.dumps(event, separators=(",", ":"), ensure_ascii=False)
            await response.write(
                ("event: message\ndata: " + payload + "\n\n").encode("utf-8")
            )
    except (ConnectionError, asyncio.CancelledError):
        # A dropped GET is only a stream disconnect; the session persists.
        pass
    finally:
        if session.stream is queue:
            session.stream = None
    return response


async def delete(request):
    _version(request)
    session = _session(request)
    complete = await session.runtime.close_session(session)
    # A slow device cleanup continues under the shared lock after the deadline.
    if complete is None:
        raise web.HTTPServiceUnavailable(
            text="Session terminated; device cleanup is still running and playback may remain active",
            headers={"Retry-After": "1"},
        )
    if not complete:
        raise web.HTTPInternalServerError(
            text="Session terminated; device cleanup failed and playback may remain active"
        )
    return web.Response(status=200)


def create_app(
    device_factory,
    session_timeout=900,
    max_sessions=16,
    max_inflight=16,
    max_queue=64,
    max_request_bytes=1048576,
    reap_interval=5,
    cleanup_timeout=75,
    allow_remote=False,
):
    """Create the endpoint (loopback checks unless allow_remote); device
    connections open on the first tool call."""
    for name, value in (
        ("session_timeout", session_timeout),
        ("reap_interval", reap_interval),
        ("cleanup_timeout", cleanup_timeout),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError("{} must be positive and finite".format(name))
    for name, value in (
        ("max_sessions", max_sessions),
        ("max_inflight", max_inflight),
        ("max_queue", max_queue),
        ("max_request_bytes", max_request_bytes),
    ):
        if type(value) is not int or value < 1:
            raise ValueError("{} must be a positive integer".format(name))
    app = web.Application(client_max_size=max_request_bytes, middlewares=[local_only])
    runtime = Runtime(
        device_factory,
        session_timeout,
        max_sessions,
        max_inflight,
        max_queue,
        reap_interval,
        cleanup_timeout,
    )
    app["mcp_runtime"] = runtime
    app["allow_remote"] = allow_remote
    app.router.add_post("/mcp", post)
    app.router.add_get("/mcp", get, allow_head=False)
    app.router.add_delete("/mcp", delete)
    app.on_startup.append(runtime.start)
    app.on_shutdown.append(runtime.shutdown)
    return app


def crestron_main(module_info):
    """Crestron Python module entry. Startup args: [port (8766), config path (config.json),
    bind address (0.0.0.0)]. No authentication: anyone who can reach the port can use it.
    Crestron -> module JSON: {"cmd":"tools"}, {"cmd":"status"} or {"Running":"False"} to stop.
    Tool calls go through the client module over HTTP. Status and debug text go back via module_info.set()."""
    bridge = cbridge.Bridge(module_info, "server")
    args = module_info.args or []
    port = int(args[0].strip()) if args and args[0].strip().isdigit() else 8766
    config = args[1].strip() if len(args) > 1 and args[1].strip() else "config.json"
    host = args[2].strip() if len(args) > 2 and args[2].strip() else "0.0.0.0"
    if not os.path.isabs(config):
        config = os.path.join(cbridge.ROOT, config)

    # TEMP DEBUG: confirm paths, config and imports from the module host. Remove when verified.
    bridge.log("DBG here={} cwd={}".format(cbridge.ROOT, os.getcwd()))
    bridge.log("DBG config={} exists={}".format(config, os.path.isfile(config)))
    bridge.log("DBG sys.path[:3]={}".format(sys.path[:3]))
    for name in ("aiohttp", "websockets", "yarl", "helpers.cbridge", "protocol", "runtime", "crestron.config",
                 "crestron.device", "crestron.controller", "crestron.mp2", "crestron.rest",
                 "crestron.workflow"):
        try:
            mod = __import__(name, fromlist=["_"])
            bridge.log("DBG import {} OK ({})".format(name, getattr(mod, "__file__", "?")))
        except Exception as exc:
            bridge.log("DBG import {} FAILED: {!r}".format(name, exc))
    try:
        from crestron.config import load_config as _lc
        _cfg = _lc(config)
        bridge.log("DBG config loaded OK device_ip={} player={}".format(_cfg.device_ip, _cfg.player))
    except Exception as exc:
        bridge.log("DBG config load FAILED: {!r}".format(exc))

    def device_factory():
        from crestron.config import load_config
        from crestron.device import Device

        return Device(load_config(config))

    loop = asyncio.new_event_loop()
    state = {}

    async def start():
        # AppRunner, not web.run_app: run_app installs signal handlers, which
        # only work on a process's main thread.
        app = create_app(device_factory, allow_remote=not is_loopback(host))
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.TCPSite(runner, host, port).start()
        state["runner"], state["app"] = runner, app

    def run(coro, timeout=170):
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=timeout)

    def handle(msg):
        cmd = msg.get("cmd")
        try:
            if cmd == "tools":
                bridge.send({"event": "tools", "result": [t["name"] for t in TOOL_DEFINITIONS]})
            elif cmd == "status":
                rt = state["app"]["mcp_runtime"]
                bridge.send({"event": "status", "sessions": len(rt.sessions)})
            else:
                bridge.log("unknown cmd {}".format(cmd))
        except Exception as exc:
            bridge.send({"event": "error", "cmd": cmd, "error": str(exc)})

    threading.Thread(target=loop.run_forever, daemon=True).start()
    try:
        run(start(), timeout=30)
        bridge.listen(handle)
        bridge.send({"status": "Running", "port": port})
        bridge.log("MCP server on {}:{}, config {}".format(host, port, config))
        bridge.wait()
    except Exception as exc:
        bridge.send({"status": "Error: {}".format(exc)})
        bridge.log("fatal: {}".format(exc))
    finally:
        try:
            if "runner" in state:
                run(state["runner"].cleanup(), timeout=90)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)
        bridge.send({"Running": False})


def main():
    parser = argparse.ArgumentParser(
        description="Crestron demo MCP localhost Streamable HTTP server"
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--session-timeout", type=float, default=900)
    parser.add_argument("--max-sessions", type=int, default=16)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    def device_factory():
        from crestron.config import load_config
        from crestron.device import Device

        return Device(load_config(args.config))

    logging.basicConfig(level=logging.INFO)
    try:
        app = create_app(
            device_factory,
            session_timeout=args.session_timeout,
            max_sessions=args.max_sessions,
            allow_remote=not is_loopback(args.host),
        )
        web.run_app(app, host=args.host, port=args.port, access_log=None)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
