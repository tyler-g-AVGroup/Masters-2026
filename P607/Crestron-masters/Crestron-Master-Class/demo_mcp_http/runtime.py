"""HTTP sessions with isolated IDs and shared device mutation/cleanup ownership."""

import asyncio
import logging
import secrets
import threading
import time

from crestron.device import ACTIONS, Device
from crestron.errors import DemoError
from crestron.state import identity
from demo_mcp.protocol import TOOL_DEFINITIONS, DemoMcpService

LOG = logging.getLogger(__name__)
STOP = object()
_PLAYBACK_ACTIONS = ("play", "next", "previous")
_PLAYBACK_COMMANDS = ("LoadSource",) + tuple(
    ACTIONS[name] for name in _PLAYBACK_ACTIONS
)
_MUTATIONS = tuple(
    tool["name"]
    for tool in TOOL_DEFINITIONS
    if tool["annotations"]["readOnlyHint"] is False
)


def rpc_error(request_id, code, message):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


class SessionDevice:
    """Coordinate device writes and cleanup ownership for one HTTP session.

    Across all sessions: at most one MP2 connection attempt and one REST login are
    admitted per 10 s (an MP2 retry can still open a socket sooner). Item ids get a
    per-session prefix. Cancelling a request or closing its session does not cancel
    a write already started (only final server teardown can). runtime.owners says which session pauses a player at cleanup; while
    a LoadSource over another session's playback is unconfirmed, a "handoff" keeps
    both candidates until a fresh player read settles it. Test fakes (not a
    crestron Device) skip the native MP2 and REST hooks.
    """

    def __init__(self, device, session):
        self.device = device
        self.runtime = session.runtime
        self._native = isinstance(device, Device)
        self._closed = False
        if self._native:
            connect = device._mp2

            async def gated_connect():
                if device.mp2 is not None and not device.mp2.failure:
                    return self._instrument_mp2(await connect())
                async with self.runtime.connection_lock:
                    if device.mp2 is None or device.mp2.failure:
                        wait = self.runtime.connection_interval - (
                            time.monotonic() - self.runtime.last_connection
                        )
                        if wait > 0:
                            raise DemoError(
                                "MP2 connection admission is cooling down; retry in {:.0f} seconds.".format(
                                    wait
                                )
                            )
                        self.runtime.last_connection = time.monotonic()
                    return self._instrument_mp2(await connect())

            device._mp2 = gated_connect
            login = device.rest._login

            def gated_login():
                # REST login runs in an executor, so its shared gate is thread-safe.
                with self.runtime.login_lock:
                    wait = self.runtime.connection_interval - (
                        time.monotonic() - self.runtime.last_login
                    )
                    if wait > 0:
                        raise DemoError(
                            "REST login admission is cooling down; retry in {:.0f} seconds.".format(
                                wait
                            )
                        )
                    self.runtime.last_login = time.monotonic()
                return login()

            device.rest._login = gated_login
            for method in ("set_audio", "set_route"):
                original = getattr(device.rest, method)

                def rest_hook(original):
                    async def write(*args, **kwargs):
                        self.runtime.mark_writing()
                        return await original(*args, **kwargs)

                    return write

                setattr(device.rest, method, rest_hook(original))
        remember = getattr(device, "_remember", None)
        if remember is not None and hasattr(device, "ids"):

            def namespaced(entry):
                key = remember(entry)
                value = device.ids.pop(key)
                session.id_counter += 1
                opaque = "{}_{:x}".format(session.namespace, session.id_counter)
                device.ids[opaque] = value
                return opaque

            device._remember = namespaced

    def _instrument_mp2(self, client):
        if getattr(client, "_http_session_instrumented", False):
            return client
        client._http_session_instrumented = True
        # A slow navigation reply must not block a player refresh/pause.
        client.navigation_lock = asyncio.Lock()
        action = client.action

        async def control(player, action_id, *args, **kwargs):
            self.runtime.mark_writing()
            if action_id == "LoadSource":
                # Device has recorded the intended item, but dispatch is not proof
                # that it replaced the previous owner's playback.
                self.runtime.handoffs[player]["intended"] = dict(self.device.owned[player])
            elif action_id in _PLAYBACK_COMMANDS:
                self._invalidate(player)
                if player not in self.device.owned:
                    self.device.owned[player] = identity(client.players[player].data)
                self.runtime.owners[player] = self
            return await action(player, action_id, *args, **kwargs)

        client.action = control
        return client

    def __getattr__(self, name):
        return getattr(self.device, name)

    def _invalidate(self, player):
        handoff = self.runtime.handoffs.pop(player, None)
        if handoff is not None:
            for owner in (handoff["owner"], handoff["previous_owner"]):
                if owner is not None:
                    owner.device.owned.pop(player, None)
        old = self.runtime.owners.pop(player, None)
        if old is not None and old is not self:
            getattr(old.device, "owned", {}).pop(player, None)

    async def _resolve_handoff(self, player):
        handoff = self.runtime.handoffs.get(player)
        if handoff is None:
            return
        reader = self if self._native else handoff["owner"]
        if reader._closed:
            raise DemoError("Playback cleanup ownership is unresolved.")
        data = await reader.device._fresh_player(player)
        owner, item = None, None
        # Prefer the intended owner when both identities match the same item.
        for candidate, wanted in (
            (handoff["owner"], handoff["intended"]),
            (handoff["previous_owner"], handoff["previous"]),
        ):
            if wanted is not None and Device._still_ours(data, wanted):
                owner, item = candidate, wanted
                break
        self._invalidate(player)
        if owner is not None:
            # A retired session cannot perform future cleanup. The live reader
            # inherits its existing obligation rather than orphaning playback.
            if owner._closed:
                owner = reader
            owner.device.owned[player] = item
            self.runtime.owners[player] = owner
        else:
            self.device.owned.pop(player, None)

    async def change(self, name, arguments):
        player = arguments.get("player")
        claims_playback = name == "play_item" or (
            name == "player_action" and arguments.get("action") in _PLAYBACK_ACTIONS
        )
        handoff = None
        if player is not None and claims_playback:
            # Callers already hold the shared runtime mutation lock.
            await self._resolve_handoff(player)
            if self._native and name == "play_item":
                previous_owner = self.runtime.owners.get(player)
                previous = (
                    previous_owner.device.owned.get(player)
                    if previous_owner is not None else None
                )
                handoff = {
                    "owner": self, "intended": None,
                    "previous_owner": previous_owner,
                    "previous": dict(previous) if previous is not None else None,
                }
                self.runtime.handoffs[player] = handoff
        if not self._native:
            # Custom devices use change()/pause() as their write boundary.
            self.runtime.mark_writing()
            if player is not None and claims_playback:
                self._invalidate(player)
        result = None
        try:
            result = await self.device.change(name, arguments)
            return result
        finally:
            if handoff is not None:
                if handoff["intended"] is None:
                    self.runtime.handoffs.pop(player, None)  # no LoadSource was sent
                elif isinstance(result, dict) and result.get("verified"):
                    self._invalidate(player)
                    self.device.owned[player] = handoff["intended"]
                    self.runtime.owners[player] = self
                else:
                    try:
                        await self._resolve_handoff(player)
                    except Exception:
                        # Preserve both identities for cleanup or the next write.
                        pass
            if (
                not self._native
                and claims_playback
                and player is not None
                and player in getattr(self.device, "owned", {})
            ):
                self.runtime.owners[player] = self

    async def pause(self, player):
        if not self._native:
            self.runtime.mark_writing()
        result = await self.device.pause(player)
        # Keep cleanup ownership until pause is verified, so failures can be retried.
        if isinstance(result, dict) and result.get("verified"):
            self._invalidate(player)
            getattr(self.device, "owned", {}).pop(player, None)
        return result

    async def close(self):
        uncertain = False
        for player, handoff in list(self.runtime.handoffs.items()):
            if self is handoff["owner"] or self is handoff["previous_owner"]:
                try:
                    await self._resolve_handoff(player)
                except Exception:
                    uncertain = True
        owned = getattr(self.device, "owned", {})
        for player in list(owned):
            if player in self.runtime.handoffs or self.runtime.owners.get(player) is not self:
                owned.pop(player, None)
        try:
            result = await self.device.close()
            if uncertain:
                raise DemoError("Playback cleanup ownership is unresolved; playback may remain active.")
            return result
        finally:
            self._closed = True
            for player, owner in list(self.runtime.owners.items()):
                if owner is self:
                    self.runtime.owners.pop(player, None)


class Session:
    def __init__(self, runtime):
        self.runtime = runtime
        self.id = secrets.token_urlsafe(32)
        self.namespace = secrets.token_hex(8)
        self.id_counter = 0
        self.last_used = time.monotonic()
        self.closed = False
        self.requests = {}
        self.stream = None
        self.close_task = None
        self.read_lock = asyncio.Lock()
        self.service = DemoMcpService(self._make_device)

    def _make_device(self):
        return SessionDevice(self.runtime.device_factory(), self)

    def touch(self):
        self.last_used = time.monotonic()

    def notify_tools_changed(self):
        if self.service.take_tools_changed():
            self._queue_event(
                {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
            )

    def _queue_event(self, event):
        if self.stream is not None:
            # Repeated refresh notices can be dropped to make room for the latest.
            if self.stream.full():
                self.stream.get_nowait()
            self.stream.put_nowait(event)

    def cancel(self, request_id):
        record = self.requests.get(request_key(request_id))
        self._cancel(record)

    @staticmethod
    def _cancel(record):
        # Cancel once so a REST worker can drain without releasing its lock early.
        if record is not None and not record["writing"] and not record["cancelling"]:
            record["cancelling"] = True
            if record["started"]:
                record["task"].cancel()

    def start(self, message):
        key = request_key(message["id"])
        if key in self.requests:
            raise ValueError("Request id is already in flight")
        record = {"writing": False, "cancelling": False, "started": False, "task": None}

        async def execute():
            try:
                record["started"] = True
                if record["cancelling"]:
                    raise asyncio.CancelledError()
                params = message.get("params", {})
                name = params.get("name")
                lock = self.runtime.lock if name in _MUTATIONS else self.read_lock
                return await self.service.dispatch(message, lock=lock)
            except asyncio.CancelledError:
                return rpc_error(message["id"], -32800, "Request cancelled")
            except Exception as exc:
                # Device/provider exception text is untrusted and can contain
                # credentials; log the type without the message or traceback.
                LOG.error("MCP request failed (%s)", type(exc).__name__)
                return rpc_error(message["id"], -32603, "Internal error")
            finally:
                self.requests.pop(key, None)
                self.runtime.requests.pop(asyncio.current_task(), None)
                self.touch()
                self.notify_tools_changed()

        task = asyncio.create_task(execute())
        record["task"] = task
        self.requests[key] = record
        self.runtime.requests[task] = record
        return task

    def begin_close(self):
        if self.close_task is None:
            self.closed = True
            self._queue_event(STOP)
            self.close_task = asyncio.create_task(self._close())
        return self.close_task

    async def _close(self):
        tasks = []
        for record in list(self.requests.values()):
            self._cancel(record)
            tasks.append(record["task"])
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        # Join discovery before close() can cancel its draining REST worker again.
        listing = list(self.service._listing_tasks)
        if listing:
            await asyncio.gather(*listing, return_exceptions=True)
        try:
            async with self.runtime.lock:
                await self.service.close()
        except Exception as exc:
            # Avoid credentials/device error text in normal HTTP responses.
            LOG.error(
                "MCP session cleanup failed (%s); playback may remain active",
                type(exc).__name__,
            )
            return False
        finally:
            self.runtime.sessions.pop(self.id, None)
        return True


def request_key(request_id):
    # JSON-RPC numeric ids compare as numbers, strings remain distinct.
    return ("string" if isinstance(request_id, str) else "number", request_id)


class Runtime:
    def __init__(
        self,
        device_factory,
        session_timeout,
        max_sessions,
        max_inflight,
        max_queue,
        reap_interval,
        cleanup_timeout,
    ):
        self.device_factory = device_factory
        self.session_timeout = session_timeout
        self.max_sessions = max_sessions
        self.max_inflight = max_inflight
        self.max_queue = max_queue
        self.reap_interval = reap_interval
        self.cleanup_timeout = cleanup_timeout
        self.sessions = {}
        self.requests = {}
        self.owners = {}
        self.handoffs = {}
        self.lock = None
        self.connection_lock = None
        self.connection_interval = 10
        self.last_connection = float("-inf")
        self.login_lock = threading.Lock()
        self.last_login = float("-inf")
        self.reaper = None
        self.stopping = False

    def mark_writing(self):
        record = self.requests.get(asyncio.current_task())
        if record is not None:
            record["writing"] = True

    async def start(self, app):
        # Made here, on the serving loop: before Python 3.10 an asyncio.Lock binds
        # to the loop that is current when it is created.
        self.lock = asyncio.Lock()
        self.connection_lock = asyncio.Lock()
        self.reaper = asyncio.create_task(self.reap())

    async def reap(self):
        while True:
            await asyncio.sleep(self.reap_interval)
            now = time.monotonic()
            for session in list(self.sessions.values()):
                if (
                    not session.closed
                    and not session.requests
                    and now - session.last_used >= self.session_timeout
                ):
                    session.begin_close()

    async def close_session(self, session):
        task = session.begin_close()
        done, _ = await asyncio.wait([task], timeout=self.cleanup_timeout)
        return task.result() if done else None

    async def shutdown(self, app):
        self.stopping = True
        if self.reaper is not None:
            self.reaper.cancel()
            await asyncio.gather(self.reaper, return_exceptions=True)
        tasks = [session.begin_close() for session in list(self.sessions.values())]
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=self.cleanup_timeout)
            if pending:
                LOG.error(
                    "MCP shutdown cleanup deadline exceeded for %d sessions; "
                    "writes may still be finishing",
                    len(pending),
                )
