"""Hand-written MCP server: JSON-RPC rules, tool arguments and the approval gate."""

import asyncio
import io
import json
import sys
import time
from unittest import TestCase
from unittest.mock import patch

from crestron.errors import DemoError
from demo_mcp import protocol
from demo_mcp.protocol import PROTOCOL_VERSION, TOOL_DEFINITIONS, DemoMcpService
from demo_mcp.server import serve_stdio


class FakeDevice:
    """Stands in for crestron.device.Device; state drives the preview fingerprint."""

    def __init__(self):
        self.calls = []
        self.state = "volume 20"
        self.closed = False
        self.fail_change = None

    async def profiles(self):
        self.calls.append("profiles")
        return {"profiles": [{"profile": "Profile1", "name": "Family", "services": 1}]}

    async def browse(self, profile, service, folder, page):
        self.calls.append(("browse", profile, service, folder, page))
        return {"profile": profile, "service": service, "items": []}

    async def preview(self, tool, args):
        self.calls.append(("preview", tool))
        return {"change": "{} {}".format(tool, args)}, self.state

    async def change(self, tool, args):
        self.calls.append(("change", tool, dict(args)))
        if self.fail_change:
            raise self.fail_change
        return {"verified": True}

    async def pause(self, player):
        self.calls.append(("pause", player))
        return {"verified": True, "player": {"player": player, "state": "paused"}}

    async def close(self):
        self.closed = True


class ListingDevice(FakeDevice):
    """A FakeDevice that also lists profiles, players, zones and inputs."""

    def __init__(self):
        super().__init__()
        self.zones_listed = [{"zone": "Zone1", "name": "Zone_Amp1"}, {"zone": "Zone2", "name": "Zone_Amp2"}]
        self.unreachable = None

    async def profiles(self):
        if self.unreachable:
            raise self.unreachable
        return {"profiles": [{"profile": "Profile1", "name": "Family", "services": 1}]}

    async def players(self):
        return {"players": [{"player": "Player01", "state": "paused"}]}

    async def zones(self):
        return {"zones": list(self.zones_listed)}

    async def inputs(self):
        return {"inputs": [{"input": "Input05", "name": "Streaming 1"}]}


def run(coro):
    return asyncio.run(coro)


async def initialized(service):
    response = await service.dispatch(
        {
            "jsonrpc": "2.0",
            "id": "init-1",
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
    )
    assert response["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert response["result"]["serverInfo"]["name"] == "crestron-demo"
    await service.dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"})


async def tool(mcp, name, **arguments):
    response = await mcp.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    return response


def result(response):
    return response["result"]["structuredContent"], response["result"]["isError"]


async def listed(service):
    response = await service.dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    return {t["name"]: t for t in response["result"]["tools"]}


class McpProtocolTests(TestCase):
    def test_json_rpc_errors_and_id_correlation(self):
        device = FakeDevice()
        service = DemoMcpService(lambda: device)

        async def scenario():
            before = await service.dispatch(
                {"jsonrpc": "2.0", "id": 44, "method": "tools/list"}
            )
            self.assertEqual(before["error"]["code"], -32002)
            await initialized(service)
            unknown = await service.dispatch(
                {"jsonrpc": "2.0", "id": "abc", "method": "unknown"}
            )
            self.assertEqual((unknown["id"], unknown["error"]["code"]), ("abc", -32601))
            invalid = await service.dispatch({"jsonrpc": "1.0", "id": 5, "method": "ping"})
            self.assertEqual(invalid["error"]["code"], -32600)
            invalid_id = await service.dispatch(
                {"jsonrpc": "2.0", "id": {"x": 1}, "method": "ping"}
            )
            self.assertIsNone(invalid_id["id"])
            ping = await service.dispatch({"jsonrpc": "2.0", "id": "k", "method": "ping"})
            self.assertEqual(ping, {"jsonrpc": "2.0", "id": "k", "result": {}})
            # A tools/call notification has no reply channel, so it must do nothing.
            silent = await service.dispatch(
                {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "pause"}}
            )
            self.assertIsNone(silent)

        run(scenario())
        self.assertEqual(device.calls, [])

    def test_tool_list_labels_reads_and_changes(self):
        service = DemoMcpService(FakeDevice)

        async def scenario():
            await initialized(service)
            listed = await service.dispatch(
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
            )
            return {t["name"]: t for t in listed["result"]["tools"]}

        tools = run(scenario())
        self.assertEqual(len(tools), 15)
        for name in ("play_item", "player_action", "set_volume", "set_mute", "set_route"):
            self.assertTrue(tools[name]["annotations"]["destructiveHint"], name)
            self.assertIn("confirm", tools[name]["inputSchema"]["properties"])
        for name in ("list_profiles", "browse", "search", "list_zones", "list_players"):
            self.assertTrue(tools[name]["annotations"]["readOnlyHint"], name)
        self.assertFalse(tools["pause"]["annotations"]["readOnlyHint"])
        self.assertNotIn("confirm", tools["pause"]["inputSchema"]["properties"])

    def test_bad_arguments_never_reach_the_device(self):
        device = FakeDevice()
        service = DemoMcpService(lambda: device)

        async def scenario():
            await initialized(service)
            for name, arguments in (
                ("set_volume", {"zone": "Zone1"}),  # missing percent
                ("set_volume", {"zone": "Zone1", "percent": 10.0}),  # not an integer
                ("set_volume", {"zone": "Zone1", "percent": True}),  # bool is not int
                ("set_mute", {"zone": "Zone1", "muted": 1}),
                ("search", {"profile": "p", "service": "s", "text": "x", "category": "Song"}),
                ("list_zones", {"extra": 1}),
                ("player_action", {"player": "Player01", "action": "stop"}),
            ):
                response = await tool(service, name, **arguments)
                self.assertEqual(response["error"]["code"], -32602, (name, arguments))
            unknown = await tool(service, "prepare_demo")
            self.assertEqual(unknown["error"]["code"], -32602)

        run(scenario())
        self.assertEqual(device.calls, [])

    def test_reads_route_to_the_device(self):
        device = FakeDevice()
        service = DemoMcpService(lambda: device)

        async def scenario():
            await initialized(service)
            profiles, error = result(await tool(service, "list_profiles"))
            self.assertFalse(error)
            self.assertEqual(profiles["profiles"][0]["profile"], "Profile1")
            await tool(service, "browse", profile="Profile1", service="Provider7", folder="i3")

        run(scenario())
        self.assertEqual(
            device.calls, ["profiles", ("browse", "Profile1", "Provider7", "i3", None)]
        )

    def test_a_change_needs_a_preview_then_a_matching_confirm(self):
        device = FakeDevice()
        service = DemoMcpService(lambda: device)

        async def scenario():
            await initialized(service)
            preview, error = result(await tool(service, "set_volume", zone="Zone1", percent=25))
            self.assertFalse(error)
            self.assertIn("preview", preview)
            token = preview["token"]
            self.assertNotIn(("change", "set_volume", {"zone": "Zone1", "percent": 25}), device.calls)

            denied = [
                {"zone": "Zone1", "percent": 25, "confirm": True},  # no token
                {"zone": "Zone1", "percent": 25, "confirm": True, "token": "forged"},
                {"zone": "Zone1", "percent": 30, "confirm": True, "token": token},  # other args
            ]
            for arguments in denied:
                failure, error = result(await tool(service, "set_volume", **arguments))
                self.assertTrue(error, arguments)
            # The mismatched attempt used the token up: previews are single use.
            replay, error = result(
                await tool(service, "set_volume", zone="Zone1", percent=25, confirm=True, token=token)
            )
            self.assertTrue(error)
            self.assertIn("preview again", replay["error"])

            fresh = result(await tool(service, "set_volume", zone="Zone1", percent=25))[0]
            done, error = result(
                await tool(service, "set_volume", zone="Zone1", percent=25, confirm=True, token=fresh["token"])
            )
            self.assertFalse(error)
            self.assertEqual(done, {"verified": True})
            again, error = result(
                await tool(service, "set_volume", zone="Zone1", percent=25, confirm=True, token=fresh["token"])
            )
            self.assertTrue(error)  # one approval, one change

        run(scenario())
        changes = [call for call in device.calls if call[0] == "change"]
        self.assertEqual(changes, [("change", "set_volume", {"zone": "Zone1", "percent": 25})])

    def test_state_change_or_expiry_voids_the_approval(self):
        device = FakeDevice()
        service = DemoMcpService(lambda: device)

        async def scenario():
            await initialized(service)
            first = result(await tool(service, "set_mute", zone="Zone1", muted=True))[0]
            device.state = "volume 80"  # someone changed the zone after the preview
            stale, error = result(
                await tool(service, "set_mute", zone="Zone1", muted=True, confirm=True, token=first["token"])
            )
            self.assertTrue(error)
            self.assertIn("changed since the preview", stale["error"])
            self.assertIn("preview", stale["details"])

            second = result(await tool(service, "set_mute", zone="Zone1", muted=True))[0]
            later = __import__("time").monotonic() + 121
            with patch("demo_mcp.protocol.time.monotonic", return_value=later):
                expired, error = result(
                    await tool(service, "set_mute", zone="Zone1", muted=True, confirm=True, token=second["token"])
                )
            self.assertTrue(error)

        run(scenario())
        self.assertFalse([call for call in device.calls if call[0] == "change"])

    def test_failed_change_says_it_may_have_applied(self):
        device = FakeDevice()
        device.fail_change = RuntimeError("timed out")
        service = DemoMcpService(lambda: device)

        async def scenario():
            await initialized(service)
            first = result(await tool(service, "play_item", player="Player01", item="i4"))[0]
            failure, error = result(
                await tool(service, "play_item", player="Player01", item="i4", confirm=True, token=first["token"])
            )
            self.assertTrue(error)
            self.assertIn("may or may not have applied", failure["error"])

        run(scenario())

    def test_pause_needs_no_approval_and_close_reaches_the_device(self):
        device = FakeDevice()
        service = DemoMcpService(lambda: device)

        async def scenario():
            await initialized(service)
            paused, error = result(await tool(service, "pause", player="Player01"))
            self.assertFalse(error)
            self.assertEqual(paused["player"]["state"], "paused")
            await service.close()

        run(scenario())
        self.assertEqual(device.calls, [("pause", "Player01")])
        self.assertTrue(device.closed)

    def test_every_tool_schema_is_closed(self):
        for spec in TOOL_DEFINITIONS:
            self.assertFalse(spec["inputSchema"]["additionalProperties"], spec["name"])

    def test_stdio_stdout_contains_only_json_rpc_and_eof_closes_cleanly(self):
        stdin = io.StringIO('not json\n{"jsonrpc":"2.0","id":"p","method":"ping"}\n')
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(sys, "stdin", stdin), patch.object(
            sys, "stdout", stdout
        ), patch.object(sys, "stderr", stderr):
            run(serve_stdio("unused-config.json"))
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["error"]["code"], -32700)
        self.assertEqual(json.loads(lines[1]), {"jsonrpc": "2.0", "id": "p", "result": {}})
        self.assertEqual(stderr.getvalue(), "")


class ValidIdTests(TestCase):
    def test_enums_and_names_come_from_the_device_when_it_is_reachable(self):
        service = DemoMcpService(ListingDevice)

        async def scenario():
            await initialized(service)
            return await listed(service)

        tools = run(scenario())
        properties = lambda name: tools[name]["inputSchema"]["properties"]  # noqa: E731
        self.assertEqual(properties("set_volume")["zone"]["enum"], ["Zone1", "Zone2"])
        self.assertEqual(
            properties("set_volume")["zone"]["description"], "Zone1 = Zone_Amp1; Zone2 = Zone_Amp2"
        )
        self.assertEqual(properties("play_item")["player"]["enum"], ["Player01"])
        self.assertEqual(properties("pause")["player"]["enum"], ["Player01"])
        self.assertEqual(properties("browse")["profile"]["description"], "Profile1 = Family")
        # Routing to nothing is valid, so '' stays in the input enum.
        self.assertEqual(properties("set_route")["input"]["enum"], ["", "Input05"])
        self.assertIn("'' = none", properties("set_route")["input"]["description"])
        # Items, stations and songs are never enumerated.
        self.assertNotIn("enum", properties("play_item")["item"])
        self.assertNotIn("enum", properties("browse")["service"])
        # The shared definitions are copied, not edited.
        for spec in TOOL_DEFINITIONS:
            for key in ("player", "zone", "profile", "input"):
                self.assertNotIn("enum", spec["inputSchema"]["properties"].get(key, {}))

    def test_an_unreachable_device_lists_the_tools_without_enums_and_without_error(self):
        device = ListingDevice()
        device.unreachable = DemoError("REST device unreachable")
        service = DemoMcpService(lambda: device)

        async def scenario():
            await initialized(service)
            return await listed(service)

        tools = run(scenario())
        self.assertEqual(len(tools), 15)
        for tool in tools.values():
            for key in ("profile", "player", "zone", "input"):
                self.assertNotIn("enum", tool["inputSchema"]["properties"].get(key, {}))

    def test_a_device_that_never_answers_does_not_hold_up_the_listing(self):
        class Hung(ListingDevice):
            async def profiles(self):
                await asyncio.sleep(30)

        service = DemoMcpService(Hung)

        async def scenario():
            await initialized(service)
            with patch.object(protocol, "_LISTING_SECONDS", 0.05):
                return await listed(service)

        tools = run(scenario())
        self.assertNotIn("enum", tools["set_volume"]["inputSchema"]["properties"]["zone"])

    def test_a_read_that_is_slow_to_cancel_does_not_hold_up_the_listing(self):
        class Stalled(ListingDevice):
            async def profiles(self):  # like RestClient._serial: cancel waits for urllib
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    await asyncio.sleep(0.5)
                    raise

        service = DemoMcpService(Stalled)

        async def scenario():
            await initialized(service)
            with patch.object(protocol, "_LISTING_SECONDS", 0.05):
                started = time.monotonic()
                tools = await listed(service)
                return time.monotonic() - started, tools

        elapsed, tools = run(scenario())
        self.assertLess(elapsed, 0.4)
        self.assertNotIn("enum", tools["set_volume"]["inputSchema"]["properties"]["zone"])

    def test_close_waits_for_a_listing_read_that_is_still_winding_down(self):
        order = []

        class Winding(ListingDevice):
            async def profiles(self):  # mid-login: cancel only takes effect after the worker
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    await asyncio.sleep(0.2)
                    order.append("read finished")  # e.g. the REST token is created here
                    raise

            async def close(self):
                order.append("device closed")  # logs out whatever the read left behind

        service = DemoMcpService(Winding)

        async def scenario():
            await initialized(service)
            with patch.object(protocol, "_LISTING_SECONDS", 0.05):
                await listed(service)  # past its deadline, the read is still running
            self.assertEqual(order, [])
            started = time.monotonic()
            await service.close()
            return time.monotonic() - started

        waited = run(scenario())
        self.assertEqual(order, ["read finished", "device closed"])
        self.assertLess(waited, 1)

    def test_cancelling_tools_list_cancels_the_read(self):
        seen = []

        class Reading(ListingDevice):
            async def profiles(self):
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    seen.append("cancelled")
                    raise

        service = DemoMcpService(Reading)

        async def scenario():
            await initialized(service)
            listing = asyncio.ensure_future(listed(service))
            await asyncio.sleep(0.05)
            listing.cancel()
            await asyncio.gather(listing, return_exceptions=True)
            await asyncio.sleep(0.05)
            self.assertEqual(service._listing_tasks, set())
            await service.close()

        run(scenario())
        self.assertEqual(seen, ["cancelled"])

    def test_a_stale_enum_never_turns_a_valid_call_into_a_protocol_error(self):
        device = ListingDevice()
        service = DemoMcpService(lambda: device)

        async def scenario():
            await initialized(service)
            await listed(service)  # Zone3 is not in the enum
            return result(await tool(service, "set_volume", zone="Zone3", percent=20))

        preview, error = run(scenario())
        self.assertFalse(error)  # reached the device, which does the real check
        self.assertIn("set_volume", device.calls[-1])

    def test_list_changed_is_declared_and_follows_changes_in_the_ids(self):
        device = ListingDevice()
        device.unreachable = DemoError("down")
        service = DemoMcpService(lambda: device)

        async def scenario():
            init = await service.dispatch(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                }
            )
            self.assertEqual(init["result"]["capabilities"]["tools"], {"listChanged": True})
            await tool(service, "list_zones")  # before any listing: nothing to tell
            self.assertFalse(service.take_tools_changed())
            await listed(service)  # device down: listed without ids
            device.unreachable = None
            await tool(service, "list_zones")  # the ids are now known
            self.assertTrue(service.take_tools_changed())
            await tool(service, "list_zones")  # same ids
            self.assertFalse(service.take_tools_changed())
            await listed(service)
            device.zones_listed.append({"zone": "Zone3", "name": "Patio"})
            await tool(service, "list_zones")
            self.assertTrue(service.take_tools_changed())
            self.assertFalse(service.take_tools_changed())  # reported once
            tools = await listed(service)
            return tools["set_volume"]["inputSchema"]["properties"]["zone"]["enum"]

        self.assertEqual(run(scenario()), ["Zone1", "Zone2", "Zone3"])

    def test_stdio_sends_the_notification_after_the_response(self):
        lines = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                "clientInfo": {"name": "t", "version": "1"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "list_zones", "arguments": {}}},
        ]  # fmt: skip
        device = ListingDevice()
        device.unreachable = DemoError("down at first")
        stdin = io.StringIO("".join(json.dumps(line) + "\n" for line in lines))
        stdout = io.StringIO()

        with patch.object(sys, "stdin", stdin), patch.object(sys, "stdout", stdout), patch(
            "crestron.config.load_config"
        ), patch("crestron.device.Device", side_effect=lambda config: device):
            original = device.zones

            async def zones():  # the device comes up after the listing
                device.unreachable = None
                return await original()

            device.zones = zones
            run(serve_stdio("unused.json"))
        out = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(out[-1], {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        self.assertEqual(out[-2]["id"], 3)


class ElicitFlowTests(TestCase):
    """The service side of approval through the client; the SDK server supplies elicit."""

    def call(self, elicit, device=None, **arguments):
        device = device or FakeDevice()
        service = DemoMcpService(lambda: device)
        arguments = arguments or {"zone": "Zone1", "percent": 40}

        async def scenario():
            return await service.call_tool("set_volume", arguments, elicit)

        return run(scenario())["structuredContent"], device

    def test_accept_makes_the_change_with_the_same_checks_as_a_token(self):
        asked = []

        async def accept(message):
            asked.append(message)
            return True

        done, device = self.call(accept)
        self.assertEqual(done, {"verified": True})
        self.assertEqual(len(asked), 1)
        self.assertTrue(asked[0].endswith(". Go ahead?"))
        self.assertIn("set_volume", asked[0])  # the preview's change text
        self.assertEqual(
            [c for c in device.calls if c[0] == "change"],
            [("change", "set_volume", {"zone": "Zone1", "percent": 40})],
        )
        self.assertEqual(device.calls.count(("preview", "set_volume")), 2)  # shown, then re-checked

    def test_accept_after_the_device_moved_on_changes_nothing(self):
        device = FakeDevice()

        async def accept_late(message):
            device.state = "volume 80"  # someone else changed the zone meanwhile
            return True

        failure, device = self.call(accept_late, device)
        self.assertIn("changed since the preview", failure["error"])
        self.assertFalse([c for c in device.calls if c[0] == "change"])

    def test_decline_changes_nothing(self):
        async def decline(message):
            return False

        done, device = self.call(decline)
        self.assertEqual(done, {"result": "Not changed: the user declined."})
        self.assertFalse([c for c in device.calls if c[0] == "change"])

    def test_no_answer_within_the_window_changes_nothing(self):
        async def silent(message):
            await asyncio.sleep(30)

        with patch.object(protocol, "_APPROVAL_TTL_SECONDS", 0.05):
            done, device = self.call(silent)
        self.assertTrue(done["result"].startswith("Not changed: no answer"))
        self.assertFalse([c for c in device.calls if c[0] == "change"])

    def test_a_client_that_cannot_be_asked_gets_the_preview_and_token(self):
        async def broken(message):
            raise RuntimeError("no back-channel")

        preview, device = self.call(broken)
        self.assertIn("token", preview)
        self.assertFalse([c for c in device.calls if c[0] == "change"])

    def test_without_elicit_the_token_flow_is_unchanged(self):
        preview, device = self.call(None)
        self.assertIn("token", preview)
        self.assertIn("expires_in_seconds", preview)

    def test_the_lock_is_free_while_the_user_decides_and_held_for_the_device_steps(self):
        device, seen = FakeDevice(), {}

        async def scenario():
            lock = asyncio.Lock()
            service = DemoMcpService(lambda: device)

            async def accept(message):
                seen["asking"] = lock.locked()
                return True

            original = device.preview

            async def preview(tool, args):
                seen.setdefault("preview", []).append(lock.locked())
                return await original(tool, args)

            device.preview = preview
            return await service.call_tool("set_volume", {"zone": "Zone1", "percent": 40}, accept, lock)

        done = run(scenario())["structuredContent"]
        self.assertEqual(done, {"verified": True})
        self.assertEqual(seen, {"asking": False, "preview": [True, True]})

    def test_a_token_still_works_when_elicit_is_available(self):
        device = FakeDevice()
        service = DemoMcpService(lambda: device)

        async def never(message):
            raise AssertionError("must not ask when a token is given")

        async def scenario():
            first = (await service.call_tool("set_mute", {"zone": "Zone1", "muted": True}))["structuredContent"]
            return await service.call_tool(
                "set_mute", {"zone": "Zone1", "muted": True, "confirm": True, "token": first["token"]}, never
            )

        self.assertEqual(run(scenario())["structuredContent"], {"verified": True})
