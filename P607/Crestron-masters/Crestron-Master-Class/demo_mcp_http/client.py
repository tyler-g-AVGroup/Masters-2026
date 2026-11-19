"""HTTP menu client for a running Crestron demo MCP server."""

import argparse
import asyncio
import json
import signal
import sys
from typing import Any, Dict, Optional

import aiohttp

if __package__ is None:  # run as python demo_mcp_http/client.py
    from pathlib import Path

    sys.path[0] = str(Path(__file__).resolve().parents[1])

from demo_mcp.client import McpClientError, Menu
from demo_mcp.protocol import PROTOCOL_VERSION

# Above one tool call's device waits (connect retry, 12 s replies, 15 s player
# checks) plus queueing behind other sessions' changes.
_TIMEOUT_SECONDS = 150
_MAX_SSE_EVENT_BYTES = 1024 * 1024
_MAX_SSE_EVENTS = 100


class HttpClient:
    """MCP Streamable HTTP client implementing the interface used by Menu."""

    def __init__(self, url: str, timeout: float = _TIMEOUT_SECONDS) -> None:
        self.url = url
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        )
        self.session_id: Optional[str] = None
        self._next_id = 1
        self._closed = False

    @classmethod
    async def connect(cls, url: str, timeout: float = _TIMEOUT_SECONDS) -> "HttpClient":
        client = cls(url, timeout)
        try:
            result = await client.request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "crestron-demo-http-client",
                        "version": "0.1.0",
                    },
                },
                initializing=True,
            )
            if (
                not isinstance(result, dict)
                or result.get("protocolVersion") != PROTOCOL_VERSION
            ):
                raise McpClientError(
                    "Server did not negotiate MCP {}".format(PROTOCOL_VERSION)
                )
            await client.notify("notifications/initialized")
            return client
        except BaseException:
            # Initialization may have allocated a session before failing.
            try:
                await client.close()
            except McpClientError:
                pass
            raise

    def _headers(self, initializing: bool = False) -> Dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if not initializing:
            if not self.session_id:
                raise McpClientError(
                    "MCP HTTP session is unavailable; restart and browse again"
                )
            headers["Mcp-Session-Id"] = self.session_id
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
        return headers

    async def request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        initializing: bool = False,
    ) -> Any:
        if self._closed:
            raise McpClientError("MCP HTTP client is closed")
        request_id = self._next_id
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        try:
            async with self.session.post(
                self.url,
                json=message,
                headers=self._headers(initializing),
            ) as response:
                if initializing:
                    self.session_id = response.headers.get("Mcp-Session-Id")
                await self._check_status(
                    response,
                    "MCP HTTP request",
                    session_required=not initializing,
                )
                content_type = (
                    response.headers.get("Content-Type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                if content_type == "application/json":
                    try:
                        payload = await response.json()
                    except (ValueError, UnicodeDecodeError):
                        raise McpClientError("MCP server returned invalid JSON")
                    result = self._response_result(payload, request_id)
                elif content_type == "text/event-stream":
                    result = await self._read_sse(response, request_id)
                else:
                    raise McpClientError(
                        "MCP server returned unsupported content type {!r}".format(
                            content_type
                        )
                    )
        except asyncio.TimeoutError:
            raise McpClientError(
                "Timed out waiting for MCP response to {}".format(method)
            )
        except aiohttp.ClientError as exc:
            raise McpClientError("MCP HTTP request failed: {}".format(exc))

        return result

    @staticmethod
    def _response_result(frame: Any, request_id: int) -> Any:
        if not isinstance(frame, dict) or frame.get("jsonrpc") != "2.0":
            raise McpClientError("MCP server returned an invalid JSON-RPC response")
        if type(frame.get("id")) is not int or frame.get("id") != request_id:
            raise McpClientError(
                "MCP response id did not match the outstanding request"
            )
        if "error" in frame:
            error = frame["error"]
            if not isinstance(error, dict):
                raise McpClientError("MCP server returned an invalid JSON-RPC error")
            raise McpClientError(
                "MCP {} error: {}".format(error.get("code"), error.get("message"))
            )
        if "result" not in frame:
            raise McpClientError("MCP response did not include result or error")
        return frame["result"]

    @staticmethod
    async def _read_sse(response: aiohttp.ClientResponse, request_id: int) -> Any:
        """Read through notifications and return as soon as this request replies."""
        import codecs

        decoder = codecs.getincrementaldecoder("utf-8")()
        pending = ""
        data_lines = []
        event_count = 0

        def parse_event():
            nonlocal data_lines, event_count
            event_count += 1
            if event_count > _MAX_SSE_EVENTS:
                raise McpClientError(
                    "MCP server sent too many SSE events before its response"
                )
            try:
                message = json.loads("\n".join(data_lines))
            except ValueError:
                raise McpClientError("MCP server sent invalid JSON in SSE data")
            data_lines = []
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                raise McpClientError(
                    "MCP server sent an invalid JSON-RPC message in SSE"
                )
            if "id" not in message and "method" in message:
                return False, None
            return True, HttpClient._response_result(message, request_id)

        async for chunk in response.content.iter_chunked(4096):
            pending += decoder.decode(chunk)
            if len(pending.encode("utf-8")) > _MAX_SSE_EVENT_BYTES + 4096:
                raise McpClientError("MCP server sent an oversized SSE event")
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                line = line.rstrip("\r")
                if not line:
                    if data_lines:
                        result = parse_event()
                        if result[0]:
                            return result[1]
                elif line.startswith("data:"):
                    value = line[5:]
                    data_lines.append(value[1:] if value.startswith(" ") else value)
                    if (
                        sum(len(part.encode("utf-8")) for part in data_lines)
                        > _MAX_SSE_EVENT_BYTES
                    ):
                        raise McpClientError("MCP server sent an oversized SSE event")
                # event/id/retry/comment fields do not carry JSON-RPC content.
        pending += decoder.decode(b"", final=True)
        if pending.startswith("data:"):
            value = pending[5:]
            data_lines.append(value[1:] if value.startswith(" ") else value)
        if data_lines:
            result = parse_event()
            if result[0]:
                return result[1]
        raise McpClientError("MCP server closed the response stream without a reply")

    async def notify(
        self, method: str, params: Optional[Dict[str, Any]] = None
    ) -> None:
        if self._closed:
            raise McpClientError("MCP HTTP client is closed")
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        try:
            async with self.session.post(
                self.url, json=message, headers=self._headers()
            ) as response:
                await self._check_status(
                    response,
                    "MCP HTTP notification",
                    session_required=True,
                )
        except asyncio.TimeoutError:
            raise McpClientError("Timed out sending MCP notification {}".format(method))
        except aiohttp.ClientError as exc:
            raise McpClientError("MCP HTTP request failed: {}".format(exc))

    @staticmethod
    async def _check_status(
        response: aiohttp.ClientResponse,
        operation: str,
        session_required: bool = False,
    ) -> None:
        if 200 <= response.status < 300:
            return
        if response.status == 404 and session_required:
            raise McpClientError(
                "MCP HTTP session expired; restart the client and browse again"
            )
        detail = (await response.text())[:500] or response.reason
        raise McpClientError(
            "{} failed with HTTP {}: {}".format(operation, response.status, detail)
        )

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        result = await self.request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        if not isinstance(result, dict):
            raise McpClientError("Tool {} returned an invalid result".format(name))
        if result.get("isError"):
            raise McpClientError(
                "Tool {} failed: {}".format(name, result.get("structuredContent", {}))
            )
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            raise McpClientError("Tool {} returned no structured result".format(name))
        return structured

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        failure = None
        try:
            if self.session_id:
                async with self.session.delete(
                    self.url,
                    headers={
                        "Mcp-Session-Id": self.session_id,
                        "MCP-Protocol-Version": PROTOCOL_VERSION,
                    },
                ) as response:
                    try:
                        await self._check_status(response, "MCP session cleanup")
                    except McpClientError as exc:
                        failure = str(exc)
        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            failure = "MCP session cleanup failed: {}".format(exc)
        finally:
            await self.session.close()
        if failure:
            raise McpClientError(failure)


async def _run(args: argparse.Namespace) -> int:
    client = None
    exit_code = 0
    # As in demo_mcp/client.py: let Ctrl-C reach a blocking input() prompt.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        client = await HttpClient.connect(args.url)
        await Menu(client).run()
    except (McpClientError, OSError, ValueError) as exc:
        print("MCP client error: {}".format(exc), file=sys.stderr)
        exit_code = 1
    finally:
        if client is not None:
            try:
                await client.close()
            except McpClientError as exc:
                print("MCP client cleanup error: {}".format(exc), file=sys.stderr)
                exit_code = 1
            if exit_code == 0:
                print("Connections closed")
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Crestron MCP menu client over HTTP")
    parser.add_argument(
        "--url", default="http://127.0.0.1:8000/mcp", help="Running MCP HTTP endpoint"
    )
    try:
        return asyncio.run(_run(parser.parse_args()))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
