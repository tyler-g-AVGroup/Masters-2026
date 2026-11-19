"""Official-SDK server: same tools and approval rules as demo_mcp. Skips where the SDK is absent."""

import asyncio
import io
import unittest
from unittest.mock import patch

from demo_mcp.protocol import TOOL_DEFINITIONS
from demo_mcp_sdk import available

HAVE_SDK = available()
SPEC = {spec["name"]: spec for spec in TOOL_DEFINITIONS}
if HAVE_SDK:
    import mcp_types as types
    from mcp import Client

    from demo_mcp import protocol


class FakeDevice:
    def __init__(self):
        self.calls = []
        self.closed = False

    async def preview(self, tool, args):
        self.calls.append(("preview", tool))
        await asyncio.sleep(0.05)  # lets a concurrent call try to slip in
        return {"change": tool}, "same"

    async def change(self, tool, args):
        self.calls.append(("change", tool, dict(args)))
        return {"verified": True}

    async def pause(self, player):
        self.calls.append(("pause", player))
        return {"verified": True}

    async def zones(self):
        return {"zones": []}

    async def close(self):
        self.closed = True


class ListingDevice(FakeDevice):
    """Lists the ids the schemas are filled from; preview/change as in FakeDevice."""

    def __init__(self):
        super().__init__()
        self.listed = {"Zone1": "Zone_Amp1", "Zone2": "Zone_Amp2"}
        self.down = False

    async def preview(self, tool, args):
        self.calls.append(("preview", tool))
        return {"change": "Zone_Amp1: volume 30% -> 40%"}, "same"

    async def profiles(self):
        if self.down:
            raise RuntimeError("device unreachable")
        return {"profiles": [{"profile": "Profile1", "name": "Family"}]}

    async def players(self):
        return {"players": [{"player": "Player01"}]}

    async def zones(self):
        return {"zones": [{"zone": key, "name": name} for key, name in self.listed.items()]}

    async def inputs(self):
        return {"inputs": [{"input": "Input05", "name": "Streaming 1"}]}


class SdkClientGuardTests(unittest.TestCase):
    def test_missing_sdk_prints_the_install_line_instead_of_a_traceback(self):
        from demo_mcp_sdk.client import main

        stderr = io.StringIO()
        with patch("importlib.util.find_spec", return_value=None), patch(
            "sys.stderr", stderr
        ):
            self.assertEqual(main(), 1)
        self.assertIn("pip install -r requirements.txt", stderr.getvalue())


@unittest.skipUnless(HAVE_SDK, "official MCP SDK not installed (Python 3.10+)")
class SdkServerTests(unittest.IsolatedAsyncioTestCase):
    def server(self, device):
        from demo_mcp_sdk.server import build_server

        return build_server(lambda: device)

    async def test_tools_match_the_custom_server(self):
        async with Client(self.server(FakeDevice())) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        self.assertEqual(set(tools), {spec["name"] for spec in TOOL_DEFINITIONS})
        for spec in TOOL_DEFINITIONS:
            tool = tools[spec["name"]]
            schema = spec["inputSchema"]
            self.assertEqual(tool.description, spec["description"])
            self.assertEqual(
                tool.annotations.model_dump(by_alias=True, exclude_none=True),
                spec["annotations"],
            )
            self.assertEqual(set(tool.input_schema.get("required", [])), set(schema["required"]))
            self.assertEqual(set(tool.input_schema["properties"]), set(schema["properties"]))

    async def test_preview_then_confirm_and_one_change_per_token(self):
        device = FakeDevice()
        async with Client(self.server(device)) as client:
            first = await client.call_tool("set_volume", {"zone": "Zone1", "percent": 25})
            self.assertFalse(first.is_error)
            token = first.structured_content["token"]
            confirm = {"zone": "Zone1", "percent": 25, "confirm": True, "token": token}
            done = await client.call_tool("set_volume", confirm)
            self.assertFalse(done.is_error, done.structured_content)
            replay = await client.call_tool("set_volume", confirm)
            self.assertTrue(replay.is_error)
            float_volume = await client.call_tool("set_volume", {"zone": "Zone1", "percent": 25.5})
            self.assertTrue(float_volume.is_error)
            paused = await client.call_tool("pause", {"player": "Player01"})
            self.assertFalse(paused.is_error)
        changes = [call for call in device.calls if call[0] == "change"]
        self.assertEqual(changes, [("change", "set_volume", {"zone": "Zone1", "percent": 25})])
        self.assertTrue(device.closed)  # lifespan cleanup ran on disconnect

    async def test_concurrent_confirms_of_one_token_change_once(self):
        device = FakeDevice()
        async with Client(self.server(device)) as client:
            token = (
                await client.call_tool("set_mute", {"zone": "Zone1", "muted": True})
            ).structured_content["token"]
            confirm = {"zone": "Zone1", "muted": True, "confirm": True, "token": token}
            results = await asyncio.gather(
                client.call_tool("set_mute", confirm), client.call_tool("set_mute", confirm)
            )
        self.assertEqual(sorted(r.is_error for r in results), [False, True])
        self.assertEqual(len([c for c in device.calls if c[0] == "change"]), 1)

    async def test_known_difference_extra_arguments_are_ignored(self):
        async with Client(self.server(FakeDevice())) as client:
            result = await client.call_tool("list_zones", {"bogus": True})
        # The custom server rejects this with -32602; the SDK drops the extra key.
        self.assertFalse(result.is_error)


@unittest.skipUnless(HAVE_SDK, "official MCP SDK not installed (Python 3.10+)")
class SdkIdsAndApprovalTests(unittest.IsolatedAsyncioTestCase):
    """Valid ids in the schemas, list_changed, and approval through elicitation.

    Elicitation and list_changed ride the initialize handshake (mode="legacy");
    the 2026-07-28 protocol has no server-to-client requests.
    """

    def server(self, device):
        from demo_mcp_sdk.server import build_server

        return build_server(lambda: device)

    @staticmethod
    def answering(action, confirm=True, asked=None):
        async def callback(context, params):
            if asked is not None:
                asked.append(params)
            return types.ElicitResult(action=action, content={"confirm": confirm} if action == "accept" else None)

        return callback

    async def test_enums_present_when_the_device_answers_and_absent_when_not(self):
        device = ListingDevice()
        async with Client(self.server(device)) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            zone = tools["set_volume"].input_schema["properties"]["zone"]
            self.assertEqual(zone["enum"], ["Zone1", "Zone2"])
            self.assertEqual(zone["description"], "Zone1 = Zone_Amp1; Zone2 = Zone_Amp2")
            self.assertEqual(tools["pause"].input_schema["properties"]["player"]["enum"], ["Player01"])
            self.assertEqual(tools["set_route"].input_schema["properties"]["input"]["enum"], ["", "Input05"])
            self.assertNotIn("enum", tools["play_item"].input_schema["properties"]["item"])
        device.down = True
        async with Client(self.server(device)) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            self.assertEqual(len(tools), 15)
            self.assertNotIn("enum", tools["set_volume"].input_schema["properties"]["zone"])
            # A listing never changes the schema the SDK validates calls against.
            done = await client.call_tool("set_volume", {"zone": "Zone9", "percent": 20})
            self.assertFalse(done.is_error)

    async def test_list_changed_is_declared_and_sent_when_the_ids_change(self):
        device = ListingDevice()
        messages = []

        async def handler(message):
            messages.append(message)

        async with Client(self.server(device), mode="legacy", message_handler=handler) as client:
            self.assertTrue(client.server_capabilities.tools.list_changed)
            await client.list_tools()
            await client.call_tool("list_zones", {})
            self.assertFalse([m for m in messages if isinstance(m, types.ToolListChangedNotification)])
            device.listed["Zone3"] = "Patio"
            await client.call_tool("list_zones", {})
            await asyncio.sleep(0.05)
            changed = [m for m in messages if isinstance(m, types.ToolListChangedNotification)]
            self.assertEqual(len(changed), 1)

    async def test_changed_ids_do_not_break_a_read_on_the_2026_07_28_protocol(self):
        device = ListingDevice()
        async with Client(self.server(device)) as client:
            self.assertEqual(client.protocol_version, "2026-07-28")
            await client.list_tools()
            device.listed["Zone3"] = "Patio"
            zones = await client.call_tool("list_zones", {})
            self.assertFalse(zones.is_error, zones.structured_content)
            self.assertEqual(len(zones.structured_content["zones"]), 3)

    async def test_one_call_asks_the_user_and_changes_on_accept(self):
        device, asked = ListingDevice(), []
        callback = self.answering("accept", asked=asked)
        async with Client(self.server(device), mode="legacy", elicitation_callback=callback) as client:
            done = await client.call_tool("set_volume", {"zone": "Zone1", "percent": 40})
        self.assertFalse(done.is_error, done.structured_content)
        self.assertEqual(done.structured_content, {"verified": True})
        self.assertEqual(asked[0].message, "Zone_Amp1: volume 30% -> 40%. Go ahead?")
        schema = asked[0].requested_schema
        self.assertEqual(list(schema["properties"]), ["confirm"])
        self.assertEqual(schema["properties"]["confirm"]["type"], "boolean")
        changes = [c for c in device.calls if c[0] == "change"]
        self.assertEqual(changes, [("change", "set_volume", {"zone": "Zone1", "percent": 40})])

    async def test_decline_cancel_and_an_unticked_box_change_nothing(self):
        for action, confirm in (("decline", True), ("cancel", True), ("accept", False)):
            device = ListingDevice()
            callback = self.answering(action, confirm)
            async with Client(self.server(device), mode="legacy", elicitation_callback=callback) as client:
                done = await client.call_tool("set_mute", {"zone": "Zone1", "muted": True})
            self.assertFalse(done.is_error, (action, done.structured_content))
            self.assertEqual(done.structured_content, {"result": "Not changed: the user declined."})
            self.assertFalse([c for c in device.calls if c[0] == "change"], action)

    async def test_no_answer_in_the_window_changes_nothing_and_frees_the_server(self):
        device, release = ListingDevice(), asyncio.Event()

        async def silent(context, params):
            await release.wait()
            return types.ElicitResult(action="cancel")

        async with Client(self.server(device), mode="legacy", elicitation_callback=silent) as client:
            try:
                with patch.object(protocol, "_APPROVAL_TTL_SECONDS", 0.2):
                    done = await client.call_tool("set_volume", {"zone": "Zone1", "percent": 40})
                self.assertTrue(done.structured_content["result"].startswith("Not changed: no answer"))
                self.assertFalse([c for c in device.calls if c[0] == "change"])
                paused = await asyncio.wait_for(client.call_tool("pause", {"player": "Player01"}), 5)
                self.assertFalse(paused.is_error)  # the lock came back after the timeout
            finally:
                release.set()

    async def test_pause_is_not_held_up_while_the_user_decides(self):
        device, release, asking = ListingDevice(), asyncio.Event(), asyncio.Event()

        async def slow(context, params):
            asking.set()
            await release.wait()
            return types.ElicitResult(action="accept", content={"confirm": True})

        async with Client(self.server(device), mode="legacy", elicitation_callback=slow) as client:
            change = asyncio.ensure_future(client.call_tool("set_volume", {"zone": "Zone1", "percent": 40}))
            try:
                await asyncio.wait_for(asking.wait(), 5)
                paused = await asyncio.wait_for(client.call_tool("pause", {"player": "Player01"}), 5)
                self.assertFalse(paused.is_error)
                self.assertFalse([c for c in device.calls if c[0] == "change"])
            finally:
                release.set()
            done = await asyncio.wait_for(change, 5)
        self.assertEqual(done.structured_content, {"verified": True})

    async def test_cancelling_a_pending_approval_leaves_the_server_usable(self):
        device, release, asking = ListingDevice(), asyncio.Event(), asyncio.Event()

        async def slow(context, params):
            asking.set()
            await release.wait()
            return types.ElicitResult(action="cancel")

        async with Client(self.server(device), mode="legacy", elicitation_callback=slow) as client:
            change = asyncio.ensure_future(client.call_tool("set_mute", {"zone": "Zone1", "muted": True}))
            try:
                await asyncio.wait_for(asking.wait(), 5)
                change.cancel()
                await asyncio.gather(change, return_exceptions=True)
                release.set()
                paused = await asyncio.wait_for(client.call_tool("pause", {"player": "Player01"}), 5)
                self.assertFalse(paused.is_error)
                again = await asyncio.wait_for(client.call_tool("set_mute", {"zone": "Zone1", "muted": True}), 5)
                self.assertEqual(again.structured_content, {"result": "Not changed: the user declined."})
            finally:
                release.set()
        self.assertFalse([c for c in device.calls if c[0] == "change"])

    async def test_a_timeout_never_releases_a_lock_another_call_holds(self):
        class Busy(ListingDevice):
            active = peak = 0

            async def pause(self, player):
                Busy.active += 1
                Busy.peak = max(Busy.peak, Busy.active)
                await asyncio.sleep(0.15)
                Busy.active -= 1
                return {"verified": True}

        device, release, asking = Busy(), asyncio.Event(), asyncio.Event()

        async def silent(context, params):
            asking.set()
            await release.wait()
            return types.ElicitResult(action="cancel")

        async with Client(self.server(device), mode="legacy", elicitation_callback=silent) as client:
            try:
                with patch.object(protocol, "_APPROVAL_TTL_SECONDS", 0.2):
                    change = asyncio.ensure_future(client.call_tool("set_volume", {"zone": "Zone1", "percent": 40}))
                    await asyncio.wait_for(asking.wait(), 5)
                    # Pauses keep the lock busy across the moment the approval times out.
                    pauses = [client.call_tool("pause", {"player": "Player01"}) for _ in range(4)]
                    results = await asyncio.wait_for(asyncio.gather(change, *pauses), 10)
            finally:
                release.set()
        self.assertEqual(Busy.peak, 1)  # never two calls on the device at once
        self.assertTrue(results[0].structured_content["result"].startswith("Not changed: no answer"))
        self.assertFalse([r for r in results[1:] if r.is_error])

    async def test_a_stalled_device_does_not_hold_up_the_listing_or_other_calls(self):
        class Stalled(ListingDevice):
            async def profiles(self):  # slow to cancel, like a stalled REST read
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    await asyncio.sleep(0.5)
                    raise

        device = Stalled()
        async with Client(self.server(device), mode="legacy") as client:
            with patch.object(protocol, "_LISTING_SECONDS", 0.1):
                listing = asyncio.ensure_future(client.list_tools())
                await asyncio.sleep(0.02)
                paused = await asyncio.wait_for(client.call_tool("pause", {"player": "Player01"}), 0.3)
                self.assertFalse(paused.is_error)  # not queued behind the listing
                tools = await asyncio.wait_for(listing, 0.4)
            self.assertNotIn("enum", {t.name: t for t in tools.tools}["set_volume"].input_schema["properties"]["zone"])

    async def test_a_client_without_elicitation_keeps_the_preview_and_token_flow(self):
        device = ListingDevice()
        async with Client(self.server(device), mode="legacy") as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            self.assertEqual(tools["set_volume"].description, SPEC["set_volume"]["description"])
            self.assertIn("returns a preview and a token", tools["set_volume"].description)
            first = await client.call_tool("set_volume", {"zone": "Zone1", "percent": 40})
            self.assertIn("token", first.structured_content)
            self.assertFalse([c for c in device.calls if c[0] == "change"])
            confirm = {"zone": "Zone1", "percent": 40, "confirm": True, "token": first.structured_content["token"]}
            done = await client.call_tool("set_volume", confirm)
            self.assertEqual(done.structured_content, {"verified": True})

    async def test_descriptions_follow_what_the_client_can_do(self):
        device = ListingDevice()
        callback = self.answering("accept")
        async with Client(self.server(device), mode="legacy", elicitation_callback=callback) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
        self.assertIn("The user is asked to approve it", tools["set_volume"].description)
        self.assertNotIn("returns a preview and a token", tools["set_volume"].description)
        self.assertEqual(tools["pause"].description, SPEC["pause"]["description"])
        # 2026-07-28 clients declare elicitation but have no back-channel: tokens.
        async with Client(self.server(device), elicitation_callback=callback) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            self.assertIn("returns a preview and a token", tools["set_volume"].description)
            first = await client.call_tool("set_volume", {"zone": "Zone1", "percent": 40})
            self.assertIn("token", first.structured_content)


if __name__ == "__main__":
    unittest.main()
