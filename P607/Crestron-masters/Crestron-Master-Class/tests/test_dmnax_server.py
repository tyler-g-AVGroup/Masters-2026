"""The real clients (crestron.Controller and crestron.Device) against dmnax-server.

The server runs in-process on a free port with a throwaway certificate. These tests
prove the clients and the demo server agree; they say nothing about real hardware.
"""

import importlib.util
import json
import ssl
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from aiohttp import web
    _spec = importlib.util.spec_from_file_location("dmnax_server", ROOT / "dmnax-server" / "server.py")
    dmnax = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(dmnax)
    from device_model import Device as FakeDevice  # put on sys.path by dmnax-server/server.py
except ImportError as exc:  # aiohttp missing: skip rather than fail the whole suite
    dmnax, SKIP = None, str(exc)
else:
    SKIP = None

from crestron.config import Config  # noqa: E402
from crestron.controller import Controller  # noqa: E402
from crestron.device import Device  # noqa: E402
from crestron.errors import DemoError  # noqa: E402


@unittest.skipIf(dmnax is None, "dmnax-server needs aiohttp: {}".format(SKIP))
class DmnaxServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tls = tempfile.TemporaryDirectory()
        self.fake = FakeDevice(players=5, zones=5, log_to_console=False)
        self.app = dmnax.create_app(self.fake)
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0,
                           ssl_context=dmnax.tls_context(Path(self.tls.name)))
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        values = dmnax.client_config("127.0.0.1:{}".format(self.port))
        values.update(timeout=5, initial_seconds=1, resume_seconds=1)
        self.config = Config(**values)
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            try:
                await client.close()
            except DemoError:
                pass
        await self.runner.cleanup()
        self.tls.cleanup()

    def device(self, **changes):
        config = Config(**dict(vars(self.config), **changes))
        client = Device(config)
        self.clients.append(client)
        return client

    # --- the direct demo -----------------------------------------------------------------

    async def test_direct_demo_sequence(self):
        controller = Controller(self.config)
        self.clients.append(controller)
        plan = await controller.prepare()
        self.assertEqual(plan["zone"]["key"], "Zone1")
        self.assertEqual(plan["input"], "Input05")
        self.assertEqual(plan["track"]["browse_path"], ["Popular stations", "Harbor FM"])
        status = await controller.load_track()
        self.assertEqual(status["state"], "playing")
        self.assertEqual((await controller.pause())["state"], "paused")
        self.assertEqual((await controller.set_volume(10))["volume"], 10.0)
        self.assertEqual((await controller.play())["state"], "playing")
        await controller.pause()
        self.assertEqual(self.fake.zones["Zone1"]["Volume"], 100)
        self.assertEqual(self.fake.players["Player01"].state, "paused")

    # --- MCP tool layer: reads -------------------------------------------------------------

    async def test_reads(self):
        device = self.device()
        profiles = (await device.profiles())["profiles"]
        self.assertEqual([p["profile"] for p in profiles], ["Profile1", "Profile2"])
        services = (await device.services("Profile1"))["services"]
        self.assertEqual({s["name"] for s in services}, {"Internet Radio", "DemoStream"})
        self.assertTrue(all(s["signed_in"] for s in services))

        root = await device.browse("Profile1", "Provider2")
        self.assertEqual([i["name"] for i in root["items"]],
                         ["Playlists", "Albums", "Artists", "New Releases"])
        playlists = await device.browse("Profile1", "Provider2", folder=root["items"][0]["id"])
        big = next(i for i in playlists["items"] if i["name"] == "Big Mix")
        first = await device.browse("Profile1", "Provider2", folder=big["id"])
        second = await device.browse("Profile1", "Provider2", page=first["next_page"])
        third = await device.browse("Profile1", "Provider2", page=second["next_page"])
        self.assertEqual([len(p["items"]) for p in (first, second, third)], [20, 20, 5])
        self.assertNotIn("next_page", third)
        self.assertTrue(all(i["playable"] for i in first["items"]))

        hits = await device.search("Profile1", "Provider2", "Aurora", "album")
        self.assertEqual({i["name"] for i in hits["items"]}, {"Northern Glass", "Paper Satellites"})
        with self.assertRaisesRegex(DemoError, "Unknown profile"):  # refused at once, no timeout
            await device.search("NoSuchProfile", "Provider2", "x", "song")

        home = await device.home("Profile1")
        self.assertEqual({i["section"] for i in home["items"]},
                         {"Internet Radio: Popular stations", "DemoStream: Playlists"})
        favorites = await device.favorites("Profile1")
        self.assertEqual([i["name"] for i in favorites["items"]][:2], ["Harbor FM", "Smoky Room Jazz"])

        zones = (await device.zones())["zones"]
        self.assertEqual([z["name"] for z in zones][:2], ["Kitchen", "Living Room"])
        self.assertEqual(zones[0]["source_player"], "Player01")
        inputs = (await device.inputs())["inputs"]
        self.assertEqual(sum(i["type"] == "MediaPlayer" for i in inputs), 5)
        players = (await device.players())["players"]
        self.assertEqual(len(players), 5)

    # --- MCP tool layer: changes -------------------------------------------------------------

    async def test_player_changes(self):
        device = self.device()
        album = (await device.search("Profile1", "Provider2", "Northern Glass", "album"))["items"][0]
        tracks = (await device.browse("Profile1", "Provider2", folder=album["id"]))["items"]
        played = await device.change("play_item", {"player": "Player02", "item": tracks[0]["id"]})
        self.assertEqual(played["player"]["title"], tracks[0]["name"])
        self.assertIn("NextTrack", played["player"]["actions"])

        async def act(action, value=None):
            args = {"player": "Player02", "action": action}
            if value is not None:
                args["value"] = value
            return (await device.change("player_action", args))["player"]

        self.assertEqual((await act("next"))["title"], tracks[1]["name"])
        self.assertEqual((await act("previous"))["title"], tracks[0]["name"])
        self.assertGreaterEqual((await act("seek", 60))["position"], 59)
        self.assertGreaterEqual((await act("forward"))["position"], 74)
        self.assertLess((await act("rewind"))["position"], 70)
        self.assertTrue((await act("shuffle", True))["shuffle"])
        self.assertEqual((await act("repeat", "list"))["repeat"], 2)
        self.assertEqual((await device.pause("Player02"))["player"]["state"], "paused")
        self.assertEqual((await act("play"))["state"], "playing")
        self.assertEqual(await device.close(), ["Player02"])  # pauses what it started
        self.clients.remove(device)
        self.assertEqual(self.fake.players["Player02"].state, "paused")

    async def test_zone_changes(self):
        device = self.device()
        result = await device.change("set_volume", {"zone": "Zone3", "percent": 35})
        self.assertEqual(result["zone"]["volume"], 35.0)
        result = await device.change("set_mute", {"zone": "Zone3", "muted": True})
        self.assertTrue(result["zone"]["muted"])
        result = await device.change("set_route", {"zone": "Zone3", "input": "Input01"})
        self.assertEqual(result["zone"]["source_name"], "Analog 1")
        result = await device.change("set_route", {"zone": "Zone3", "input": ""})
        self.assertIsNone(result["zone"]["source"])
        preview, _ = await device.preview("set_volume", {"zone": "Zone2", "percent": 40})
        self.assertEqual(preview["change"], "Living Room: volume 25% -> 40%")

    # --- faults and refusals ------------------------------------------------------------------

    async def test_refused_load_is_reported(self):
        device = self.device()
        station = (await device.search("Profile1", "Provider1", "Jazz", "station"))["items"][0]
        self.fake.faults["refuse_load"] = True
        with self.assertRaisesRegex(DemoError, "refused the command: Set Station Failed"):
            await device.change("play_item", {"player": "Player03", "item": station["id"]})
        self.assertEqual(self.fake.players["Player03"].state, "stopped")

    async def test_tampered_signed_data_is_refused(self):
        device = self.device()
        station = (await device.search("Profile1", "Provider1", "Harbor", "station"))["items"][0]
        device.ids[station["id"]]["item"]["SignedData"]["SourceData"]["Node"] = "ir:news:1"
        with self.assertRaisesRegex(DemoError, "invalid SignedData"):
            await device.change("play_item", {"player": "Player04", "item": station["id"]})

    async def test_playlist_cannot_be_loaded_directly(self):
        device = self.device()
        mp2 = await device._mp2()
        await mp2.subscribe("Player05")
        playlist = self.fake.catalog.item(self.fake.catalog.nodes["ds:pl:road"])
        baseline = await mp2.load_source("Player05", "Profile1", "Provider2", playlist["SignedData"])
        with self.assertRaisesRegex(DemoError, "cannot be played directly"):
            await mp2.wait_player("Player05", baseline, "playing", "Road Trip", timeout=3)

    async def test_expired_rest_session_logs_in_again(self):
        device = self.device()
        await device.zones()
        self.assertEqual(self.app[dmnax.REST].expire_all(), 1)
        await device.zones()  # 403 -> one login -> retry
        self.assertEqual(len(self.app[dmnax.REST].sessions), 1)

    async def test_wrong_credentials_are_login_errors(self):
        with self.assertRaisesRegex(DemoError, "REST login refused"):
            await self.device(admin_password="wrong").zones()
        with self.assertRaisesRegex(DemoError, "MP2 login/handshake refused"):
            await self.device(client_secret="d3Jvbmc=").profiles()

    async def test_status_page_and_fault_api(self):
        context = ssl._create_unverified_context()
        base = "https://127.0.0.1:{}".format(self.port)

        def call(path, body=None):
            request = urllib.request.Request(
                base + path, data=json.dumps(body).encode() if body is not None else None,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, context=context) as response:
                return response.read().decode()

        self.assertIn("dmnax-server", await self._thread(call, "/"))
        state = json.loads(await self._thread(call, "/dmnax/api/state"))
        self.assertEqual(len(state["zones"]), 5)
        reply = json.loads(await self._thread(call, "/dmnax/api/faults", {"reply_delay": 0.5}))
        self.assertEqual(reply["faults"]["reply_delay"], 0.5)

    async def _thread(self, function, *args):
        import asyncio
        return await asyncio.get_running_loop().run_in_executor(None, function, *args)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    unittest.main()
