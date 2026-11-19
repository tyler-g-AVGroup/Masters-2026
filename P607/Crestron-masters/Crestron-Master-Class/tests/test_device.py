"""Device previews: what an approval is bound to."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from crestron.config import Config
from crestron.device import Device
from crestron.errors import DemoError
from crestron.state import PlayerState


CONFIG = Config("192.0.2.1", "id", "c2VjcmV0", "admin", "pw")


def station(title):
    return {
        "PlayerState": "playing",
        "AvailableActions": ["Pause"],
        "Player": {
            "ProviderKey": "Provider7",
            "NowPlayingData": {"TrackTitle": title, "StationName": "Paper FM", "Duration": 0},
        },
    }


class PreviewTests(unittest.IsolatedAsyncioTestCase):
    def device(self, data):
        device = Device(CONFIG)
        state = PlayerState()
        state.update(data)
        device.mp2 = SimpleNamespace(players={"Player01": state}, failure=None)
        device._active_player = AsyncMock(return_value=data)
        device._offered = AsyncMock(return_value=data)
        device._rest_tables = AsyncMock(return_value=({}, {}, {}, "2.0.31"))
        device._hearing = Mock(return_value=("Input05", []))
        return device

    async def test_live_radio_retitling_keeps_the_approval_valid(self):
        args = {"player": "Player01", "action": "shuffle", "value": True}
        _, before = await self.device(station("Morning Show")).preview("player_action", args)
        _, after = await self.device(station("News at the Hour")).preview("player_action", args)
        self.assertEqual(before, after)

    async def test_a_different_station_voids_the_approval(self):
        args = {"player": "Player01", "action": "shuffle", "value": True}
        other = station("Morning Show")
        other["Player"]["NowPlayingData"]["StationName"] = "Other FM"
        _, before = await self.device(station("Morning Show")).preview("player_action", args)
        _, after = await self.device(other).preview("player_action", args)
        self.assertNotEqual(before, after)

    async def test_bad_action_values_are_refused_before_the_device(self):
        device = self.device(station("x"))
        for args in (
            {"player": "Player01", "action": "seek", "value": "30"},
            {"player": "Player01", "action": "repeat", "value": "all"},
            {"player": "Player01", "action": "next", "value": 1},
        ):
            with self.assertRaises(DemoError):
                await device.preview("player_action", args)
        device._offered.assert_not_awaited()

    async def test_volume_outside_the_zone_limits_is_refused_not_clamped(self):
        device = Device(CONFIG)
        zone = {"zone": "Zone1", "name": "Gym", "volume": 20.0, "muted": False,
                "min_volume": 10.0, "max_volume": 70.0, "source": None}  # fmt: skip
        device._zone = AsyncMock(return_value=(zone, {}))
        with self.assertRaisesRegex(DemoError, "outside"):
            await device.preview("set_volume", {"zone": "Zone1", "percent": 80})
        preview, _ = await device.preview("set_volume", {"zone": "Zone1", "percent": 30})
        self.assertEqual(preview["change"], "Gym: volume 20% -> 30%")


class UnknownIdTests(unittest.IsolatedAsyncioTestCase):
    """An id the device does not list fails at once, before anything is waited for."""

    PLAYERS = {"Player01": {"PlayerState": "playing"}, "Player02": {"PlayerState": "ready"}}

    def device(self):
        device = Device(CONFIG)
        get = AsyncMock(return_value=self.PLAYERS)
        device.mp2 = SimpleNamespace(get=get, failure=None, players={})
        device.player_slots = set(self.PLAYERS)
        zones = {"Device": {"ZoneOutputs": {"Version": "2.0.31", "Zones": {
            "Zone1": {"Name": "Zone_Amp1"}, "Zone2": {"Name": "Zone_Amp2"}}}}}  # fmt: skip
        device.rest = SimpleNamespace(get=AsyncMock(return_value=zones))
        return device

    async def test_unknown_player_is_refused_without_asking_the_device_for_it(self):
        device = self.device()
        device._fresh_player = AsyncMock()
        with self.assertRaises(DemoError) as raised:
            await device.preview("player_action", {"player": "Player1", "action": "play"})
        self.assertEqual(str(raised.exception), "Unknown player 'Player1'; players are: Player01")
        device._fresh_player.assert_not_awaited()  # GetCresNextObject for it would wait 12 s
        with self.assertRaisesRegex(DemoError, "Unknown player 'Player1'"):
            await device.pause("Player1")
        with self.assertRaisesRegex(DemoError, "Unknown player 'Player1'"):
            await device.change("play_item", {"player": "Player1", "item": "i1"})
        self.assertFalse(
            [c for c in device.mp2.get.await_args_list if c.args[0].endswith("Player1")]
        )

    async def test_a_listed_but_unused_slot_keeps_its_own_message(self):
        device = self.device()
        device._fresh_player = AsyncMock(return_value=self.PLAYERS["Player02"])
        with self.assertRaisesRegex(DemoError, "Player02 is an unused player slot"):
            await device.pause("Player02")

    async def test_a_slot_that_appeared_after_connecting_is_found_by_one_re_read(self):
        device = self.device()
        device.player_slots = {"Player01"}
        device._fresh_player = AsyncMock(return_value=self.PLAYERS["Player02"])
        with self.assertRaisesRegex(DemoError, "unused player slot"):
            await device.pause("Player02")
        self.assertEqual(device.player_slots, set(self.PLAYERS))

    async def test_unknown_zone_is_refused_with_the_zones_and_their_names(self):
        device = self.device()
        for call in (
            device.preview("set_volume", {"zone": "Zone9", "percent": 20}),
            device.change("set_mute", {"zone": "Zone9", "muted": True}),
        ):
            with self.assertRaises(DemoError) as raised:
                await call
            self.assertEqual(
                str(raised.exception),
                "Unknown zone 'Zone9'; zones are: Zone1 (Zone_Amp1), Zone2 (Zone_Amp2)",
            )
        paths = {c.args[0] for c in device.rest.get.await_args_list}
        self.assertEqual(paths, {"/Device/ZoneOutputs"})  # no routes or inputs read for it

    async def test_unknown_profile_is_refused_before_the_menu_request(self):
        device = self.device()
        device.mp2.get = AsyncMock(return_value={"Profile1": {"Name": "Family"}})
        device.mp2.browse = AsyncMock()
        with self.assertRaisesRegex(DemoError, "Unknown profile 'P9'; profiles are: Profile1 .Family."):
            await device.browse("P9", "Provider7")
        device.mp2.browse.assert_not_awaited()


class OwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_skip_keeps_ownership_so_shutdown_still_pauses(self):
        song = lambda title: {  # noqa: E731
            "PlayerState": "playing",
            "AvailableActions": ["Pause", "NextTrack"],
            "Player": {"NowPlayingData": {"StationName": title, "Duration": 200}},
        }
        state = PlayerState()
        state.update(song("First Song"))

        async def skipped(*args, **kwargs):
            state.update(song("Second Song"))

        mp2 = SimpleNamespace(
            players={"Player01": state}, failure=None, close=AsyncMock(),
            action=AsyncMock(return_value=0), wait_delta=AsyncMock(side_effect=skipped),
        )  # fmt: skip
        device = Device(CONFIG)
        device.mp2 = mp2
        device.owned = {"Player01": {"name": "First Song", "profile": None, "service": None}}
        device._mp2 = AsyncMock(return_value=mp2)
        device._offered = AsyncMock(return_value=state.data)
        await device._player_action({"player": "Player01", "action": "next"})
        self.assertEqual(device.owned["Player01"]["name"], "Second Song")

        device._fresh_player = AsyncMock(return_value=state.data)
        device.pause = AsyncMock()
        device.rest = SimpleNamespace(close=AsyncMock())
        await device.close()
        device.pause.assert_awaited_once_with("Player01")


    async def test_shutdown_leaves_another_service_alone(self):
        device = Device(CONFIG)
        device.mp2 = SimpleNamespace(failure=None, close=AsyncMock())
        device.rest = SimpleNamespace(close=AsyncMock())
        device.owned = {"Player01": {"name": "Song", "profile": "Profile1", "service": "Provider10"}}
        device.pause = AsyncMock()
        device._fresh_player = AsyncMock(return_value={
            "PlayerState": "playing",
            "Player": {"ProviderKey": "Provider11", "NowPlayingData": {"StationName": "Song", "Duration": 200}},
        })  # fmt: skip
        await device.close()
        device.pause.assert_not_awaited()

    async def test_lost_connection_reports_an_unconfirmed_cleanup(self):
        device = Device(CONFIG)
        device.mp2 = SimpleNamespace(failure=DemoError("lost"), close=AsyncMock())
        device.rest = SimpleNamespace(close=AsyncMock())
        device.owned = {"Player01": {"name": "Song", "profile": None, "service": None}}
        with self.assertRaisesRegex(DemoError, "may still be active"):
            await device.close()


if __name__ == "__main__":
    unittest.main()
