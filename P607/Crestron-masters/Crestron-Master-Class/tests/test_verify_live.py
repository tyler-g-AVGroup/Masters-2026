"""Exercise the verifier's failure cleanup without contacting hardware."""

from contextlib import ExitStack, redirect_stdout
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, call, patch

from crestron.errors import DemoError
from tests.verify_live import verify


class VerifierCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def failed_child(self, snapshots, wait_error=None, mute_error=None):
        mute_attempts = 0

        async def set_audio(zone, name, value):
            nonlocal mute_attempts
            if name == "IsMuted" and value is True:
                mute_attempts += 1
                if mute_attempts == 2 and mute_error is not None:
                    raise mute_error

        config = SimpleNamespace(player="Player01")
        observer = SimpleNamespace(
            config=config,
            prepare=AsyncMock(
                return_value={
                    "zone": {"key": "Zone1"},
                    "input": "Input05",
                    "player": "Player01",
                    "device": {"model": "fake"},
                    "service": {"key": "Provider10"},
                    "routed": True,
                }
            ),
            mp2=SimpleNamespace(
                players={"Player01": SimpleNamespace(data={"PlayerState": "stopped"})},
                get=AsyncMock(side_effect=snapshots),
                action=AsyncMock(return_value=7),
                wait_player=AsyncMock(side_effect=wait_error),
            ),
            rest=SimpleNamespace(
                get=AsyncMock(
                    return_value={
                        "Device": {
                            "ZoneOutputs": {
                                "Zones": {
                                    "Zone1": {
                                        "ZoneAudio": {
                                            "Volume": 300,
                                            "IsMuted": False,
                                            "MinVolume": 0,
                                        }
                                    }
                                }
                            },
                            "AvMatrixRouting": {
                                "Routes": {"Zone1": {"AudioSource": "Input05"}}
                            },
                        }
                    }
                ),
                set_audio=AsyncMock(side_effect=set_audio),
                set_route=AsyncMock(),
            ),
            close=AsyncMock(),
        )
        args = SimpleNamespace(config="unused.json", route=False)
        with ExitStack() as stack:
            stack.enter_context(patch("tests.verify_live.load_config", return_value=config))
            stack.enter_context(patch("tests.verify_live.Controller", return_value=observer))
            stack.enter_context(  # the first entry point is an MCP tool tour
                patch(
                    "tests.verify_live.tour",
                    AsyncMock(side_effect=DemoError("child failed during playback")),
                )
            )
            report_writer = stack.enter_context(patch("tests.verify_live.Path.write_text"))
            stack.enter_context(redirect_stdout(io.StringIO()))
            with self.assertRaisesRegex(DemoError, "child failed during playback"):
                await verify(args)
        observer.close.assert_awaited_once()
        report_writer.assert_called_once()
        report = json.loads(report_writer.call_args.args[0])
        return observer, report

    def assert_left_muted(self, observer, report):
        self.assertFalse(report["settings_restored"])
        self.assertTrue(report["cleanup_errors"])
        # Setup unmutes once. Cleanup must mute, restore route/volume, and stay muted.
        self.assertEqual(
            observer.rest.set_audio.await_args_list[-2:],
            [call("Zone1", "IsMuted", True), call("Zone1", "Volume", 300)],
        )
        self.assertEqual(
            observer.rest.set_audio.await_args_list.count(
                call("Zone1", "IsMuted", False)
            ),
            1,
        )

    async def test_disconnected_observer_does_not_trust_cached_stopped_state(self):
        observer, report = await self.failed_child(DemoError("MP2 connection lost"))
        observer.mp2.get.assert_awaited_once_with(
            "/Device/MediaPlayerNeXt/Players/Player01"
        )
        observer.mp2.action.assert_not_awaited()
        self.assert_left_muted(observer, report)

    async def test_missing_fresh_state_leaves_zone_muted(self):
        observer, report = await self.failed_child([{}])
        observer.mp2.action.assert_not_awaited()
        self.assert_left_muted(observer, report)

    async def test_unverified_mute_and_pause_skip_route_and_volume_restoration(self):
        observer, report = await self.failed_child(
            DemoError("MP2 connection lost"), mute_error=DemoError("mute failed")
        )
        self.assertFalse(report["settings_restored"])
        observer.rest.set_route.assert_not_awaited()
        self.assertNotIn(
            call("Zone1", "Volume", 300), observer.rest.set_audio.await_args_list
        )
        self.assertEqual(
            observer.rest.set_audio.await_args_list[-1], call("Zone1", "IsMuted", True)
        )
        self.assertTrue(
            any("mute failed" in error for error in report["cleanup_errors"])
        )
        self.assertTrue(
            any("not restored" in error for error in report["cleanup_errors"])
        )
        self.assertFalse(
            any("left muted" in error for error in report["cleanup_errors"])
        )

    async def test_fresh_playing_state_is_paused_and_read_back_before_unmuting(self):
        observer, report = await self.failed_child(
            [{"PlayerState": "playing"}, {"PlayerState": "paused"}]
        )
        observer.mp2.action.assert_awaited_once_with("Player01", "Pause")
        observer.mp2.wait_player.assert_awaited_once_with("Player01", 7, "paused")
        self.assertEqual(observer.mp2.get.await_count, 2)
        self.assertTrue(report["settings_restored"])
        self.assertEqual(report["cleanup_errors"], [])
        self.assertEqual(
            observer.rest.set_audio.await_args_list[-1],
            call("Zone1", "IsMuted", False),
        )

    async def test_pause_readback_still_playing_leaves_zone_muted(self):
        observer, report = await self.failed_child(
            [{"PlayerState": "playing"}, {"PlayerState": "playing"}]
        )
        self.assert_left_muted(observer, report)

    async def test_pause_failure_leaves_zone_muted(self):
        observer, report = await self.failed_child(
            [{"PlayerState": "playing"}], DemoError("pause outcome unknown")
        )
        self.assert_left_muted(observer, report)

    async def test_fresh_idle_state_allows_restoration_without_pause(self):
        for state in ("paused", "stopped"):
            with self.subTest(state=state):
                observer, report = await self.failed_child([{"PlayerState": state}])
                observer.mp2.get.assert_awaited_once()
                observer.mp2.action.assert_not_awaited()
                self.assertTrue(report["settings_restored"])
                self.assertEqual(report["cleanup_errors"], [])
