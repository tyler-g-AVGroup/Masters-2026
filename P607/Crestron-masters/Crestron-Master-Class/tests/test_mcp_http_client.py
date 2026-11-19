"""Focused wire tests for the Streamable HTTP menu client."""

import asyncio
import json
import unittest

try:
    from aiohttp import web
except ImportError:
    raise unittest.SkipTest("aiohttp not installed: pip install -r requirements.txt")

from demo_mcp.client import McpClientError
from demo_mcp.protocol import PROTOCOL_VERSION
from demo_mcp_http.client import HttpClient


class HttpClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.seen = []
        self.deleted = []

        async def handler(request):
            if request.method == "DELETE":
                self.deleted.append(request.headers.get("Mcp-Session-Id"))
                return web.Response(status=204)
            payload = await request.json()
            self.seen.append((payload, dict(request.headers)))
            if payload.get("method") == "initialize":
                return web.json_response(
                    {"jsonrpc": "2.0", "id": payload["id"], "result": {"protocolVersion": PROTOCOL_VERSION}},
                    headers={"Mcp-Session-Id": "session-1"},
                )
            if payload.get("method") == "notifications/initialized":
                return web.Response(status=202)
            if payload.get("method") == "explode":
                return web.json_response({"jsonrpc": "2.0", "id": payload["id"], "error": {"code": -32000, "message": "bad request"}})
            if payload.get("method") == "lost":
                return web.Response(status=404, text="session gone")
            if payload.get("method") == "wrong-id":
                return web.json_response({"jsonrpc": "2.0", "id": payload["id"] + 100, "result": {}})
            if payload.get("method") == "open-stream":
                stream = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
                await stream.prepare(request)
                message = {"jsonrpc": "2.0", "id": payload["id"], "result": {"ready": True}}
                await stream.write(("data: {}\n\n".format(json.dumps(message))).encode("utf-8"))
                await asyncio.sleep(2)
                return stream
            result = {"jsonrpc": "2.0", "id": payload["id"], "result": {"structuredContent": {"text": "café"}}}
            stream = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
            await stream.prepare(request)
            notification = b'data: {"jsonrpc":"2.0","method":"notifications/tools/list_changed"}\n\n'
            encoded = json.dumps(result, ensure_ascii=False).encode("utf-8")
            marker = "é".encode("utf-8")
            split = encoded.index(marker) + 1  # deliberately split the multibyte codepoint
            await stream.write(notification + b"data: " + encoded[:split])
            await asyncio.sleep(0)
            await stream.write(encoded[split:] + b"\n\n")
            await stream.write_eof()
            return stream

        app = web.Application()
        app.router.add_route("*", "/mcp", handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.url = "http://127.0.0.1:{}/mcp".format(port)

    async def asyncTearDown(self):
        await self.runner.cleanup()

    async def test_initialize_sse_response_headers_and_cleanup(self):
        client = await HttpClient.connect(self.url)
        self.assertEqual(client.session_id, "session-1")
        self.assertEqual(await client.call_tool("demo", {}), {"text": "café"})
        request, headers = self.seen[-1]
        self.assertEqual(request["method"], "tools/call")
        self.assertEqual(headers["Mcp-Session-Id"], "session-1")
        self.assertEqual(headers["MCP-Protocol-Version"], PROTOCOL_VERSION)
        await client.close()
        self.assertEqual(self.deleted, ["session-1"])

    async def test_protocol_error_and_expired_session_are_reported(self):
        client = await HttpClient.connect(self.url)
        with self.assertRaisesRegex(McpClientError, "MCP -32000 error: bad request"):
            await client.request("explode")
        with self.assertRaisesRegex(McpClientError, "session expired"):
            await client.request("lost")
        with self.assertRaisesRegex(McpClientError, "response id did not match"):
            await client.request("wrong-id")
        await client.close()

    async def test_sse_response_returns_before_server_closes_stream(self):
        client = await HttpClient.connect(self.url)
        self.assertEqual(await asyncio.wait_for(client.request("open-stream"), 1), {"ready": True})
        await client.close()

    async def test_cleanup_failure_is_surfaced(self):
        await self.runner.cleanup()
        async def failed_cleanup(request):
            if request.method == "DELETE":
                return web.Response(status=500, text="pause failed")
            payload = await request.json()
            if payload.get("method") == "initialize":
                return web.json_response({"jsonrpc": "2.0", "id": payload["id"], "result": {"protocolVersion": PROTOCOL_VERSION}}, headers={"Mcp-Session-Id": "session-1"})
            return web.Response(status=202)
        app = web.Application()
        app.router.add_route("*", "/mcp", failed_cleanup)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        client = await HttpClient.connect("http://127.0.0.1:{}/mcp".format(port))
        with self.assertRaisesRegex(McpClientError, "cleanup failed with HTTP 500"):
            await client.close()


if __name__ == "__main__":
    unittest.main()
