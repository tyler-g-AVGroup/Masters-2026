"""HTTP transport contract tests for the Crestron MCP server.

These exercise the public HTTP endpoint with aiohttp's real request/response path;
the fake device keeps the suite independent of hardware and network services.
"""

import asyncio
import json
import unittest
from unittest.mock import patch

from demo_mcp.protocol import PROTOCOL_VERSION, TOOL_DEFINITIONS

try:
    from aiohttp.test_utils import TestClient, TestServer
except ImportError:  # the legacy stdio environment does not install aiohttp
    TestClient = TestServer = None
else:
    from demo_mcp_http.server import create_app


class FakeDevice:
    """Small device double with observable connection and playback ownership."""

    def __init__(self):
        self.calls = []
        self.closed = False
        self.owned = {}
        self.current = {}
        self.ids = {}
        self.counter = 0
        self.paused = []
        self.state = "state-1"
        self.profile_key = "p1"
        self.browse_started = asyncio.Event()
        self.release_browse = asyncio.Event()
        self.block_browse = False
        self.block_pause = False
        self.pause_started = asyncio.Event()
        self.release_pause = asyncio.Event()
        self.block_change = False
        self.change_started = asyncio.Event()
        self.release_change = asyncio.Event()
        self.block_close = False
        self.close_started = asyncio.Event()
        self.release_close = asyncio.Event()
        self.close_error = None
        self.block_cancelled_read = False
        self.cancelled_read_started = asyncio.Event()
        self.release_cancelled_read = asyncio.Event()
        self.second_cancel_seen = False

    async def profiles(self):
        self.calls.append("profiles")
        return {"profiles": [{"profile": self.profile_key, "name": "Family", "services": 1}]}

    async def players(self):
        self.calls.append("players")
        return {"players": [{"player": "player-1", "state": "paused"}]}

    async def zones(self):
        self.calls.append("zones")
        return {"zones": [{"zone": "zone-1", "name": "Room"}]}

    async def inputs(self):
        self.calls.append("inputs")
        return {"inputs": [{"input": "input-1", "name": "Stream"}]}

    async def services(self, profile):
        self.calls.append(("services", profile))
        return {"profile": profile, "services": []}

    async def browse(self, profile, service, folder=None, page=None):
        self.calls.append(("browse", profile, service, folder, page))
        if self.block_browse:
            self.browse_started.set()
            await self.release_browse.wait()
        if folder is not None and folder not in self.ids:
            raise ValueError("unknown folder id")
        if self.block_cancelled_read:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled_read_started.set()
                try:
                    await self.release_cancelled_read.wait()
                except asyncio.CancelledError:
                    self.second_cancel_seen = True
                    raise
                raise
        return {
            "profile": profile,
            "service": service,
            "items": [{"id": self._remember({"type": "item"}), "name": "Track"}],
        }

    def _remember(self, entry):
        self.counter += 1
        key = "i{}".format(self.counter)
        self.ids[key] = entry
        return key

    async def search(self, profile, service, text, category):
        self.calls.append(("search", profile, service, text, category))
        return {"profile": profile, "service": service, "items": []}

    async def home(self, profile):
        self.calls.append(("home", profile))
        return {"profile": profile, "items": []}

    async def favorites(self, profile):
        self.calls.append(("favorites", profile))
        return {"profile": profile, "items": []}

    async def preview(self, tool, args):
        self.calls.append(("preview", tool, dict(args)))
        return {"change": "{} {}".format(tool, args)}, self.state

    async def change(self, tool, args):
        self.calls.append(("change", tool, dict(args)))
        if tool == "play_item":
            # Model two sessions starting the same source on the same player.
            player = args["player"]
            identity = "same-track"
            self.owned[player] = identity
            self.current[player] = identity
        self.state = "state-{}".format(len(self.calls))
        if self.block_change:
            self.change_started.set()
            await self.release_change.wait()
        return {"verified": True}

    async def pause(self, player):
        self.calls.append(("pause", player))
        if self.block_pause:
            self.pause_started.set()
            await self.release_pause.wait()
        self.paused.append(player)
        return {"verified": True, "player": {"player": player, "state": "paused"}}

    async def close(self):
        self.close_started.set()
        if self.block_close:
            await self.release_close.wait()
        self.closed = True
        # Mirror the device's ownership guard closely enough to catch cleanup that
        # pauses a playback this session no longer owns.
        for player, identity in list(self.owned.items()):
            if self.current.get(player) == identity:
                self.paused.append(player)
        if self.close_error is not None:
            raise self.close_error


@unittest.skipIf(TestClient is None, "aiohttp is only required by the HTTP server")
class McpHttpServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.devices = []

        def device_factory():
            device = FakeDevice()
            self.devices.append(device)
            return device

        self.client = TestClient(TestServer(create_app(device_factory)))
        await self.client.start_server()
        self.session_ids = []

    async def replace_client(self, **app_options):
        await self.client.close()
        self.devices = []

        def device_factory():
            device = FakeDevice()
            self.devices.append(device)
            return device

        self.client = TestClient(TestServer(create_app(device_factory, **app_options)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    def headers(self, session_id=None):
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
        return headers

    async def initialize(self, client=None):
        client = client or self.client
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "transport-test", "version": "1"},
            },
        }
        response = await client.post("/mcp", json=payload, headers=self.headers())
        body = await response.json()
        self.assertEqual(response.status, 200)
        self.assertEqual(body["result"]["protocolVersion"], PROTOCOL_VERSION)
        session_id = response.headers.get("Mcp-Session-Id")
        self.assertTrue(session_id)
        self.session_ids.append(session_id)
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=self.headers(session_id),
        )
        self.assertEqual(response.status, 202)
        return session_id

    async def rpc(self, session_id, method, params=None, request_id=2, client=None):
        client = client or self.client
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        response = await client.post(
            "/mcp", json=payload, headers=self.headers(session_id)
        )
        return response, await response.json()

    async def notify_cancelled(self, session_id, request_id, count=1):
        for _ in range(count):
            response = await self.client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "notifications/cancelled",
                    "params": {"requestId": request_id},
                },
                headers=self.headers(session_id),
            )
            self.assertEqual(response.status, 202)

    async def wait_for_request(self, session_id, request_id):
        session = self.client.server.app["mcp_runtime"].sessions[session_id]
        key = ("number", request_id)
        for _ in range(100):
            if key in session.requests:
                return session
            await asyncio.sleep(0.01)
        self.fail("request {} did not enter the server".format(request_id))

    async def test_initialize_does_not_open_device_and_tools_match_shared_contract(self):
        session_id = await self.initialize()
        self.assertEqual(self.devices, [], "handshake must not contact the device")

        response, body = await self.rpc(session_id, "tools/list")
        self.assertEqual(response.status, 200)
        actual = body["result"]["tools"]
        self.assertEqual([tool["name"] for tool in actual], [tool["name"] for tool in TOOL_DEFINITIONS])
        self.assertEqual(len(actual), 15)
        for actual_tool, expected_tool in zip(actual, TOOL_DEFINITIONS):
            self.assertEqual(actual_tool["inputSchema"]["type"], expected_tool["inputSchema"]["type"])
            self.assertEqual(actual_tool["inputSchema"]["required"], expected_tool["inputSchema"]["required"])
            self.assertEqual(actual_tool["inputSchema"]["additionalProperties"], False)
            self.assertEqual(actual_tool["annotations"], expected_tool["annotations"])

    async def test_http_validation_and_unknown_session_do_not_dispatch(self):
        # A request without the protocol headers is rejected before JSON-RPC.
        response = await self.client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}
        )
        self.assertGreaterEqual(response.status, 400)

        session_id = await self.initialize()
        bad = await self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            headers={**self.headers(session_id), "Origin": "https://attacker.invalid"},
        )
        self.assertGreaterEqual(bad.status, 400)

        unknown = await self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 3, "method": "ping"},
            headers=self.headers("unknown-session"),
        )
        self.assertEqual(unknown.status, 404)
        self.assertEqual(self.devices, [])

        wrong_type = await self.client.post(
            "/mcp",
            data=json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"}),
            headers={**self.headers(session_id), "Content-Type": "text/plain"},
        )
        self.assertGreaterEqual(wrong_type.status, 400)

        wrong_accept = await self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 3, "method": "ping"},
            headers={**self.headers(session_id), "Accept": "text/plain"},
        )
        self.assertGreaterEqual(wrong_accept.status, 400)

    async def test_tool_call_notification_has_no_device_side_effect(self):
        session_id = await self.initialize()
        response = await self.client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "pause", "arguments": {"player": "player-1"}},
            },
            headers=self.headers(session_id),
        )
        self.assertEqual(response.status, 202)
        self.assertEqual(self.devices, [])

    async def test_invalid_tool_names_keep_the_invalid_params_error(self):
        session_id = await self.initialize()
        for name in (None, 7, [], {}):
            response, body = await self.rpc(
                session_id, "tools/call", {"name": name, "arguments": {}}
            )
            self.assertEqual(response.status, 200)
            self.assertEqual(body["error"]["code"], -32602)
        self.assertEqual(self.devices, [])

    async def test_transport_headers_and_malformed_messages_have_precise_errors(self):
        session_id = await self.initialize()
        ping = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
        for changed, status in (({"Accept": "application/json"}, 406),
                                ({"Content-Type": "text/plain"}, 415),
                                ({"MCP-Protocol-Version": "2026-07-28"}, 400),
                                ({"Host": "attacker.invalid"}, 403),
                                ({"Origin": "https://attacker.invalid"}, 403)):
            headers = dict(self.headers(session_id), **changed)
            response = await self.client.post("/mcp", json=ping, headers=headers)
            self.assertEqual(response.status, status, changed)
        malformed = await self.client.post("/mcp", data=b'{"jsonrpc":',
                                           headers=self.headers(session_id))
        self.assertEqual(malformed.status, 400)
        self.assertEqual((await malformed.json())["error"]["code"], -32700)
        batch = await self.client.post("/mcp", json=[ping], headers=self.headers(session_id))
        self.assertEqual(batch.status, 400)
        self.assertEqual((await batch.json())["error"]["code"], -32600)
        _, unknown = await self.rpc(session_id, "unsupported/method")
        self.assertEqual(unknown["error"]["code"], -32601)
        self.assertEqual(self.devices, [])

    async def test_delete_closes_only_that_session(self):
        first = await self.initialize()
        # A read creates the service's device, allowing cleanup to be observed.
        response, _ = await self.rpc(
            first, "tools/call", {"name": "list_profiles", "arguments": {}}
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(len(self.devices), 1)

        second = await self.initialize()
        response, _ = await self.rpc(
            second, "tools/call", {"name": "list_profiles", "arguments": {}}
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(len(self.devices), 2)

        deleted = await self.client.delete(
            "/mcp", headers=self.headers(first)
        )
        self.assertLess(deleted.status, 300)
        self.assertTrue(self.devices[0].closed)
        self.assertFalse(self.devices[1].closed)

        after = await self.client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "ping"},
            headers=self.headers(first),
        )
        self.assertEqual(after.status, 404)

    async def test_delete_reports_safe_cleanup_failure_and_retires_session(self):
        session_id = await self.initialize()
        response, _ = await self.rpc(
            session_id, "tools/call", {"name": "list_profiles", "arguments": {}}
        )
        self.assertEqual(response.status, 200)
        self.devices[0].close_error = RuntimeError("secret device address and credential")

        with self.assertLogs("demo_mcp_http.runtime", level="ERROR") as captured:
            deleted = await self.client.delete("/mcp", headers=self.headers(session_id))
        self.assertNotIn("secret", "\n".join(captured.output))
        self.assertEqual(deleted.status, 500)
        body = await deleted.text()
        self.assertIn("playback may remain active", body)
        self.assertNotIn("secret", body)
        after = await self.client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 80, "method": "ping"},
            headers=self.headers(session_id),
        )
        self.assertEqual(after.status, 404)

    async def test_delete_deadline_rejects_new_requests_while_cleanup_drains(self):
        await self.replace_client(cleanup_timeout=0.03)
        session_id = await self.initialize()
        response, _ = await self.rpc(
            session_id, "tools/call", {"name": "list_profiles", "arguments": {}}
        )
        self.assertEqual(response.status, 200)
        device = self.devices[0]
        device.block_close = True

        delete_task = asyncio.create_task(
            self.client.delete("/mcp", headers=self.headers(session_id))
        )
        await asyncio.wait_for(device.close_started.wait(), timeout=1)
        deleted = await asyncio.wait_for(delete_task, timeout=1)
        self.assertEqual(deleted.status, 503)
        self.assertIn("cleanup is still running", await deleted.text())

        # The session is retired as soon as shutdown starts, even though the
        # device's close call is still running in the background.
        during_cleanup = await self.client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 81, "method": "ping"},
            headers=self.headers(session_id),
        )
        self.assertEqual(during_cleanup.status, 404)
        self.assertFalse(device.closed)

        device.release_close.set()
        for _ in range(100):
            if device.closed:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(device.closed, "timed-out cleanup must finish after it is released")

    async def test_cancelled_queued_write_does_not_apply_and_repeated_cancel_is_safe(self):
        session_id = await self.initialize()
        args = {"zone": "zone-1", "percent": 30}
        _, preview = await self.rpc(
            session_id, "tools/call", {"name": "set_volume", "arguments": args}
        )
        token = preview["result"]["structuredContent"]["token"]

        blocker = asyncio.create_task(
            self.rpc(session_id, "tools/call", {"name": "pause", "arguments": {"player": "player-1"}}, request_id=90)
        )
        device = self.devices[0]
        device.block_pause = True
        await asyncio.wait_for(device.pause_started.wait(), timeout=1)

        queued = asyncio.create_task(
            self.rpc(
                session_id,
                "tools/call",
                {"name": "set_volume", "arguments": dict(args, confirm=True, token=token)},
                request_id=91,
            )
        )
        await self.wait_for_request(session_id, 91)
        await self.notify_cancelled(session_id, 91, count=2)
        response, cancelled = await asyncio.wait_for(queued, timeout=1)
        self.assertEqual(response.status, 200)
        self.assertEqual(cancelled["error"]["code"], -32800)
        self.assertFalse(any(call[0] == "change" for call in device.calls))

        device.release_pause.set()
        await asyncio.wait_for(blocker, timeout=1)

    async def test_cancel_after_write_begins_does_not_interrupt_device_operation(self):
        session_id = await self.initialize()
        args = {"zone": "zone-1", "percent": 30}
        _, preview = await self.rpc(
            session_id, "tools/call", {"name": "set_volume", "arguments": args}
        )
        token = preview["result"]["structuredContent"]["token"]
        device = self.devices[0]
        device.block_change = True

        write = asyncio.create_task(
            self.rpc(
                session_id,
                "tools/call",
                {"name": "set_volume", "arguments": dict(args, confirm=True, token=token)},
                request_id=92,
            )
        )
        await asyncio.wait_for(device.change_started.wait(), timeout=1)
        await self.notify_cancelled(session_id, 92, count=2)
        self.assertFalse(write.done(), "cancellation must not interrupt an in-progress write")
        self.assertEqual(sum(call[0] == "change" for call in device.calls), 1)

        device.release_change.set()
        response, applied = await asyncio.wait_for(write, timeout=1)
        self.assertEqual(response.status, 200)
        self.assertFalse(applied["result"]["isError"])
        self.assertEqual(sum(call[0] == "change" for call in device.calls), 1)

    async def test_repeated_cancel_does_not_interrupt_a_draining_device_read(self):
        session_id = await self.initialize()
        device = None
        # Create the device first, then make the read emulate RestClient._serial:
        # it acknowledges one cancellation but must finish its worker before exit.
        _, _ = await self.rpc(
            session_id, "tools/call", {"name": "list_profiles", "arguments": {}}
        )
        device = self.devices[0]
        device.block_cancelled_read = True
        request = asyncio.create_task(
            self.rpc(
                session_id,
                "tools/call",
                {"name": "browse", "arguments": {"profile": "p1", "service": "svc"}},
                request_id=93,
            )
        )
        await self.wait_for_request(session_id, 93)
        # Wait until the fake read has entered before cancelling it.
        for _ in range(100):
            if any(call[0] == "browse" for call in device.calls):
                break
            await asyncio.sleep(0.01)
        await self.notify_cancelled(session_id, 93)
        await asyncio.wait_for(device.cancelled_read_started.wait(), timeout=1)
        await self.notify_cancelled(session_id, 93)
        self.assertFalse(device.second_cancel_seen)
        self.assertFalse(request.done(), "the first cancellation must wait for the read to drain")
        device.release_cancelled_read.set()
        response, cancelled = await asyncio.wait_for(request, timeout=1)
        self.assertEqual(response.status, 200)
        self.assertEqual(cancelled["error"]["code"], -32800)
        self.assertFalse(device.second_cancel_seen)

    async def test_browse_ids_are_opaque_and_cannot_cross_sessions(self):
        first = await self.initialize()
        second = await self.initialize()
        _, first_result = await self.rpc(
            first,
            "tools/call",
            {"name": "browse", "arguments": {"profile": "p1", "service": "svc"}},
        )
        first_id = first_result["result"]["structuredContent"]["items"][0]["id"]
        _, second_result = await self.rpc(
            second,
            "tools/call",
            {"name": "browse", "arguments": {"profile": "p1", "service": "svc"}},
        )
        second_id = second_result["result"]["structuredContent"]["items"][0]["id"]
        self.assertNotEqual(first_id, second_id)
        self.assertNotEqual(first_id, "i1")
        _, foreign = await self.rpc(
            second,
            "tools/call",
            {"name": "browse", "arguments": {"profile": "p1", "service": "svc", "folder": first_id}},
        )
        self.assertTrue(foreign["result"]["isError"])

    async def test_same_track_ownership_transfers_before_old_session_cleanup(self):
        first = await self.initialize()
        second = await self.initialize()

        async def play(session_id):
            args = {"player": "player-1", "item": "item-1"}
            _, preview = await self.rpc(
                session_id, "tools/call", {"name": "play_item", "arguments": args}
            )
            token = preview["result"]["structuredContent"]["token"]
            _, applied = await self.rpc(
                session_id,
                "tools/call",
                {"name": "play_item", "arguments": dict(args, confirm=True, token=token)},
            )
            self.assertFalse(applied["result"]["isError"])

        await play(first)
        await play(second)
        self.assertNotIn("player-1", self.devices[0].owned)
        self.assertEqual(self.devices[1].owned["player-1"], "same-track")

        await self.client.delete("/mcp", headers=self.headers(first))
        self.assertEqual(self.devices[0].paused, [])
        self.assertEqual(self.devices[1].paused, [])
        await self.client.delete("/mcp", headers=self.headers(second))
        self.assertEqual(self.devices[1].paused, ["player-1"])

    async def test_preview_requires_confirmation_and_token_is_session_scoped(self):
        first = await self.initialize()
        second = await self.initialize()
        args = {"zone": "zone-1", "percent": 35}
        response, body = await self.rpc(
            first, "tools/call", {"name": "set_volume", "arguments": args}
        )
        preview = body["result"]["structuredContent"]
        self.assertIn("token", preview)
        self.assertFalse(body["result"]["isError"])
        self.assertEqual([c[0] for c in self.devices[0].calls], ["preview"])

        _, mismatched = await self.rpc(
            first,
            "tools/call",
            {"name": "set_volume", "arguments": dict(args, percent=40, confirm=True, token=preview["token"])},
        )
        self.assertTrue(mismatched["result"]["isError"])
        self.assertFalse(any(call[0] == "change" for call in self.devices[0].calls))

        # The rejected token cannot be used with the original arguments either.
        _, rejected_reuse = await self.rpc(
            first,
            "tools/call",
            {"name": "set_volume", "arguments": dict(args, confirm=True, token=preview["token"])},
        )
        self.assertTrue(rejected_reuse["result"]["isError"])

        # Start a fresh approval for the valid path below.
        _, next_preview = await self.rpc(
            first, "tools/call", {"name": "set_volume", "arguments": args}
        )
        preview = next_preview["result"]["structuredContent"]

        # A token issued in one HTTP session cannot authorize another session.
        response, foreign = await self.rpc(
            second,
            "tools/call",
            {"name": "set_volume", "arguments": dict(args, confirm=True, token=preview["token"])},
        )
        self.assertEqual(response.status, 200)
        self.assertTrue(foreign["result"]["isError"])
        self.assertFalse(any(call[0] == "change" for call in self.devices[1].calls))

        response, confirmed = await self.rpc(
            first,
            "tools/call",
            {"name": "set_volume", "arguments": dict(args, confirm=True, token=preview["token"])},
        )
        self.assertFalse(confirmed["result"]["isError"])
        self.assertEqual(sum(call[0] == "change" for call in self.devices[0].calls), 1)

        # Confirmation consumes a token; replay cannot apply a second write.
        _, replay = await self.rpc(
            first,
            "tools/call",
            {"name": "set_volume", "arguments": dict(args, confirm=True, token=preview["token"])},
        )
        self.assertTrue(replay["result"]["isError"])
        self.assertEqual(sum(call[0] == "change" for call in self.devices[0].calls), 1)

    async def test_expired_and_stale_approval_tokens_never_change_device(self):
        session_id = await self.initialize()
        args = {"zone": "zone-1", "percent": 35}
        with patch("demo_mcp.protocol._APPROVAL_TTL_SECONDS", -1):
            _, response = await self.rpc(
                session_id, "tools/call", {"name": "set_volume", "arguments": args}
            )
        token = response["result"]["structuredContent"]["token"]
        _, expired = await self.rpc(
            session_id,
            "tools/call",
            {"name": "set_volume", "arguments": dict(args, confirm=True, token=token)},
        )
        self.assertTrue(expired["result"]["isError"])
        self.assertIn("expired", expired["result"]["structuredContent"]["error"])
        self.assertFalse(any(call[0] == "change" for call in self.devices[0].calls))

        _, preview = await self.rpc(
            session_id, "tools/call", {"name": "set_volume", "arguments": args}
        )
        token = preview["result"]["structuredContent"]["token"]
        self.devices[0].state = "changed-after-preview"
        _, stale = await self.rpc(
            session_id,
            "tools/call",
            {"name": "set_volume", "arguments": dict(args, confirm=True, token=token)},
        )
        self.assertTrue(stale["result"]["isError"])
        self.assertIn("changed since the preview", stale["result"]["structuredContent"]["error"])
        self.assertFalse(any(call[0] == "change" for call in self.devices[0].calls))

    async def test_stale_list_ids_notify_connected_sse_client(self):
        session_id = await self.initialize()
        _, initial = await self.rpc(session_id, "tools/list")
        self.assertEqual(initial["result"]["tools"][1]["inputSchema"]["properties"]["profile"]["enum"], ["p1"])

        get_headers = {
            "Accept": "text/event-stream",
            "Mcp-Session-Id": session_id,
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        stream = await self.client.get("/mcp", headers=get_headers)
        self.assertEqual(stream.status, 200)
        self.devices[0].profile_key = "p2"
        try:
            _, listed = await self.rpc(
                session_id,
                "tools/call",
                {"name": "list_profiles", "arguments": {}},
            )
            self.assertFalse(listed["result"]["isError"])
            body = await asyncio.wait_for(stream.content.read(2048), timeout=2)
            self.assertIn(b"notifications/tools/list_changed", body)
        finally:
            stream.close()

    async def test_slow_navigation_does_not_hold_up_pause(self):
        session_id = await self.initialize()
        device = None

        async def call(method_id, name, arguments):
            return await self.rpc(
                session_id,
                "tools/call",
                {"name": name, "arguments": arguments},
                request_id=method_id,
            )

        browse_task = asyncio.create_task(call(20, "browse", {"profile": "p1", "service": "svc"}))
        # The first tools/call lazily creates the session's device. Wait for it to
        # enter browse before starting pause, then ensure pause can make progress.
        for _ in range(100):
            if self.devices:
                device = self.devices[0]
                break
            await asyncio.sleep(0.01)
        self.assertIsNotNone(device)
        device.block_browse = True
        # If browse raced ahead of setting the gate, repeat with a fresh request.
        if not device.browse_started.is_set():
            await asyncio.sleep(0.02)
        if not device.browse_started.is_set():
            browse_task.cancel()
            await asyncio.gather(browse_task, return_exceptions=True)
            device.block_browse = True
            browse_task = asyncio.create_task(call(21, "browse", {"profile": "p1", "service": "svc"}))
            await asyncio.wait_for(device.browse_started.wait(), timeout=1)
        try:
            pause_task = asyncio.create_task(call(22, "pause", {"player": "player-1"}))
            _, pause_result = await asyncio.wait_for(pause_task, timeout=1)
            self.assertFalse(pause_result["result"]["isError"])
            self.assertTrue(any(call == ("pause", "player-1") for call in device.calls))
        finally:
            device.release_browse.set()
            await asyncio.gather(browse_task, return_exceptions=True)

    async def test_session_capacity_and_idle_expiry(self):
        await self.replace_client(max_sessions=1, session_timeout=0.08, reap_interval=0.01)
        first = await self.initialize()
        rejected = await self.client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "second", "version": "1"},
                },
            },
            headers=self.headers(),
        )
        self.assertGreaterEqual(rejected.status, 400)
        await asyncio.sleep(0.15)
        expired = await self.client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 9, "method": "ping"},
            headers=self.headers(first),
        )
        self.assertEqual(expired.status, 404)


if __name__ == "__main__":
    unittest.main()
