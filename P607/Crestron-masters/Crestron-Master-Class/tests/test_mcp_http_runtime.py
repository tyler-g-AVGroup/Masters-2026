"""Offline regressions for HTTP startup and native playback cleanup ownership."""

import asyncio
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from crestron.device import Device
from crestron.errors import DemoError
from crestron.mp2 import Mp2Client
from crestron.state import PlayerState, identity

try:
    from aiohttp import web
except ImportError:
    web = None
else:
    from demo_mcp_http.runtime import Session
    from demo_mcp_http.server import create_app


PLAYER = "Player01"


def song(title, profile="p1", service="svc1", state="playing"):
    return {
        "PlayerState": state,
        "AvailableActions": ["Play", "Pause", "NextTrack", "PreviousTrack"],
        "Player": {
            "ProfileKey": profile,
            "ProviderKey": service,
            "NowPlayingData": {"TrackTitle": title, "Duration": 200, "ElapsedSec": 0},
        },
    }


class Playback:
    def __init__(self):
        self.data = song("External")
        self.snapshots = "ok"
        self.actions = []


class ControlledMp2:
    """Separate native clients observing one physical player's playback state."""

    load_source = Mp2Client.load_source
    fresh_player = Mp2Client.fresh_player

    def __init__(self, playback):
        self.playback = playback
        self.failure = None
        self.players = {PLAYER: PlayerState()}
        self.players[PLAYER].update(playback.data)
        self.send = "accept"
        self.verify = "ok"
        self.send_started = asyncio.Event()
        self.verify_started = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False

    async def get(self, path):
        if self.playback.snapshots == "error":
            raise DemoError("Snapshot unavailable")
        if self.playback.snapshots == "unknown":
            return None
        if self.playback.snapshots == "empty":
            return {}
        data = copy.deepcopy(self.playback.data)
        self.players[PLAYER].update(data)
        return data

    async def action(self, player, action_id, options=None):
        self.playback.actions.append((self, action_id))
        if action_id == "LoadSource":
            if self.send in ("accept", "apply_error"):
                self.playback.data = song(
                    options["SignedData"]["title"], options["ProfileKey"], options["ProviderKey"]
                )
            self.send_started.set()
            if self.send == "block":
                await self.release.wait()
            if self.send in ("error", "apply_error"):
                raise DemoError("Send failed; application is unknown")
        elif action_id == "Pause":
            self.playback.data["PlayerState"] = "paused"
        return 0

    async def wait_player(self, player, baseline, expected, title=None, timeout=10):
        if expected == "playing":
            self.verify_started.set()
            if self.verify == "block":
                await self.release.wait()
            if self.verify == "error" or identity(self.playback.data)["name"] != title:
                raise DemoError("LoadSource not verified")
        self.players[player].update(copy.deepcopy(self.playback.data))
        return self.players[player].metadata()

    async def close(self):
        self.closed = True


@unittest.skipIf(web is None, "aiohttp is only required by the HTTP server")
class RuntimeStartupTests(unittest.TestCase):
    def contend_after_synchronous_construction(self, name):
        construction_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(construction_loop)
        try:
            app = create_app(lambda: self.fail("startup must not construct a device"))
        finally:
            asyncio.set_event_loop(None)
            construction_loop.close()

        async def serve():
            runner = web.AppRunner(app)
            await runner.setup()  # normal aiohttp startup, without a listening socket
            lock = getattr(app["mcp_runtime"], name)
            try:
                await lock.acquire()
                waiter = asyncio.create_task(lock.acquire())
                try:
                    await asyncio.sleep(0)
                    self.assertFalse(waiter.done(), "the second acquire must contend")
                    lock.release()
                    await asyncio.wait_for(waiter, 1)
                finally:
                    if not waiter.done():
                        waiter.cancel()
                    await asyncio.gather(waiter, return_exceptions=True)
                    if lock.locked():
                        lock.release()
            finally:
                await runner.cleanup()

        asyncio.run(serve())

    def test_operation_lock_belongs_to_serving_loop(self):
        self.contend_after_synchronous_construction("lock")

    def test_connection_lock_belongs_to_serving_loop(self):
        self.contend_after_synchronous_construction("connection_lock")


@unittest.skipIf(web is None, "aiohttp is only required by the HTTP server")
class NativeOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playback = Playback()
        self.clients = []

        def factory():
            rest = SimpleNamespace(
                _login=Mock(), set_audio=AsyncMock(), set_route=AsyncMock(), close=AsyncMock()
            )
            with patch("crestron.device.RestClient", return_value=rest):
                device = Device(None)  # no config reads, REST requests or hardware
            client = ControlledMp2(self.playback)
            self.clients.append(client)
            device.mp2 = client
            device.player_slots = {PLAYER}
            device.subscribed = {PLAYER}
            return device

        self.app = create_app(factory)
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.runtime = self.app["mcp_runtime"]
        self.first = self.session()
        self.second = self.session()

    async def asyncTearDown(self):
        self.playback.snapshots = "ok"
        await self.runner.cleanup()

    def session(self):
        session = Session(self.runtime)
        self.runtime.sessions[session.id] = session
        session.service._device_instance()
        return session

    @staticmethod
    def device(session):
        return session.service._device_instance()

    async def play(self, session, title, profile="p1", service="svc1"):
        device = self.device(session)
        item = device._remember({
            "type": "item", "profile": profile, "service": service,
            "item": {"BrowseItemName": title, "SignedData": {"title": title}},
        })
        async with self.runtime.lock:
            return await device.change("play_item", {"player": PLAYER, "item": item})

    async def refused(self, session, title="Y", send="refuse"):
        self.device(session).mp2.send = send
        with self.assertRaises(DemoError):
            await self.play(session, title)

    async def uncertain(self):
        await self.play(self.first, "X")
        self.playback.snapshots = "error"
        await self.refused(self.second)

    async def close(self, session):
        self.assertTrue(await self.runtime.close_session(session))

    async def failed_close(self, session):
        with self.assertLogs("demo_mcp_http.runtime", level="ERROR"):
            self.assertFalse(await self.runtime.close_session(session))

    def assert_owner(self, session, title):
        device = self.device(session)
        self.assertIs(self.runtime.owners.get(PLAYER), device)
        self.assertEqual(device.owned[PLAYER]["name"], title)

    def assert_pauses(self, count):
        self.assertEqual(sum(action == "Pause" for _, action in self.playback.actions), count)

    async def test_refused_replacement_restores_other_session_cleanup(self):
        await self.play(self.first, "X")
        await self.refused(self.second)
        self.assert_owner(self.first, "X")
        await self.close(self.second)
        self.assert_pauses(0)
        await self.close(self.first)
        self.assert_pauses(1)

    async def test_send_failure_restores_other_session_cleanup(self):
        await self.play(self.first, "X")
        await self.refused(self.second, send="error")
        await self.close(self.second)
        self.assert_pauses(0)
        await self.close(self.first)
        self.assert_pauses(1)

    async def test_refused_same_session_replacement_keeps_original_item(self):
        await self.play(self.first, "X")
        await self.refused(self.first)
        self.assert_owner(self.first, "X")
        await self.close(self.first)
        self.assert_pauses(1)

    async def test_send_failure_same_session_keeps_original_item(self):
        await self.play(self.first, "X")
        await self.refused(self.first, send="error")
        await self.close(self.first)
        self.assert_pauses(1)

    async def test_accepted_replacement_transfers_cleanup(self):
        await self.play(self.first, "X")
        await self.play(self.second, "Y")
        self.assert_owner(self.second, "Y")
        await self.close(self.first)
        self.assert_pauses(0)
        await self.close(self.second)
        self.assert_pauses(1)

    async def test_accepted_same_item_transfers_cleanup(self):
        await self.play(self.first, "X")
        await self.play(self.second, "X")
        await self.close(self.first)
        self.assert_pauses(0)
        await self.close(self.second)
        self.assert_pauses(1)

    async def test_same_item_failure_prefers_intended_owner(self):
        await self.play(self.first, "X")
        self.device(self.second).mp2.verify = "error"
        with self.assertRaises(DemoError):
            await self.play(self.second, "X")
        self.assert_owner(self.second, "X")
        await self.close(self.first)
        self.assert_pauses(0)
        await self.close(self.second)
        self.assert_pauses(1)

    async def test_applied_send_failure_keeps_intended_cleanup(self):
        await self.play(self.first, "X")
        await self.refused(self.second, send="apply_error")
        self.assert_owner(self.second, "Y")
        await self.close(self.first)
        self.assert_pauses(0)
        await self.close(self.second)
        self.assert_pauses(1)

    async def test_applied_verification_failure_keeps_intended_cleanup(self):
        await self.play(self.first, "X")
        self.device(self.second).mp2.verify = "error"
        with self.assertRaises(DemoError):
            await self.play(self.second, "Y")
        self.assert_owner(self.second, "Y")
        await self.close(self.first)
        self.assert_pauses(0)
        await self.close(self.second)
        self.assert_pauses(1)

    async def cancelled_load(self, same_session=False, during_send=False, applied=False):
        await self.play(self.first, "X")
        target = self.first if same_session else self.second
        client = self.device(target).mp2
        client.send = "accept" if applied else "refuse"
        if during_send:
            client.send = "block"
            started = client.send_started
        else:
            client.verify = "block"
            started = client.verify_started
        started.clear()
        task = asyncio.create_task(self.play(target, "Y"))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        return target

    async def test_cancelled_send_restores_previous_session(self):
        await self.cancelled_load(during_send=True)
        await self.close(self.second)
        self.assert_pauses(0)
        await self.close(self.first)
        self.assert_pauses(1)

    async def test_cancelled_verification_restores_previous_session(self):
        await self.cancelled_load()
        await self.close(self.second)
        self.assert_pauses(0)
        await self.close(self.first)
        self.assert_pauses(1)

    async def test_cancelled_same_session_send_keeps_previous_item(self):
        await self.cancelled_load(same_session=True, during_send=True)
        await self.close(self.first)
        self.assert_pauses(1)

    async def test_cancelled_applied_load_keeps_intended_cleanup(self):
        await self.cancelled_load(applied=True)
        await self.close(self.first)
        self.assert_pauses(0)
        await self.close(self.second)
        self.assert_pauses(1)

    async def test_delayed_old_snapshot_restores_original_owner_before_cleanup(self):
        await self.uncertain()
        self.playback.snapshots = "ok"
        await self.close(self.second)
        self.assert_pauses(0)
        self.assert_owner(self.first, "X")
        await self.close(self.first)
        self.assert_pauses(1)

    async def test_delayed_intended_snapshot_commits_new_owner_before_cleanup(self):
        await self.uncertain()
        self.playback.snapshots = "ok"
        self.playback.data = song("Y")
        await self.close(self.first)
        self.assert_pauses(0)
        self.assert_owner(self.second, "Y")
        await self.close(self.second)
        self.assert_pauses(1)

    async def test_delayed_external_snapshot_is_not_adopted(self):
        await self.uncertain()
        self.playback.snapshots = "ok"
        self.playback.data = song("External", profile="other", service="other")
        await self.close(self.first)
        await self.close(self.second)
        self.assert_pauses(0)

    async def test_matching_title_from_other_source_is_not_adopted(self):
        await self.uncertain()
        self.playback.snapshots = "ok"
        self.playback.data = song("Y", profile="other", service="other")
        await self.close(self.first)
        await self.close(self.second)
        self.assert_pauses(0)

    async def test_unknown_cleanup_reports_failure_and_retains_retired_previous_item(self):
        await self.uncertain()
        await self.failed_close(self.first)
        self.assert_pauses(0)
        self.playback.snapshots = "ok"
        await self.close(self.second)
        self.assert_pauses(1)
        self.assertEqual(self.playback.data["PlayerState"], "paused")

    async def test_unknown_cleanup_retains_retired_intended_item(self):
        await self.uncertain()
        await self.failed_close(self.second)
        self.playback.snapshots = "ok"
        self.playback.data = song("Y")
        await self.close(self.first)
        self.assert_pauses(1)

    async def test_unknown_same_session_cleanup_does_not_silently_succeed(self):
        await self.play(self.first, "X")
        self.playback.snapshots = "unknown"
        await self.refused(self.first)
        await self.failed_close(self.first)
        self.assert_pauses(0)

    async def test_unresolved_handoff_blocks_another_playback_mutation(self):
        await self.uncertain()
        third = self.session()
        before = len(self.playback.actions)
        with self.assertRaises(DemoError):
            await self.play(third, "Z")
        self.assertEqual(len(self.playback.actions), before)

    async def test_resolved_old_item_survives_another_refused_handoff(self):
        await self.uncertain()
        third = self.session()
        self.playback.snapshots = "ok"
        await self.refused(third, "Z")
        await self.close(self.second)
        await self.close(third)
        self.assert_pauses(0)
        await self.close(self.first)
        self.assert_pauses(1)

    async def test_new_accepted_owner_cannot_be_erased_by_stale_fallback(self):
        await self.uncertain()
        self.playback.snapshots = "ok"
        third = self.session()
        await self.play(third, "Z")
        await self.close(self.first)
        await self.close(self.second)
        self.assert_owner(third, "Z")
        self.assert_pauses(0)
        await self.close(third)
        self.assert_pauses(1)

    async def test_verified_pause_clears_unresolved_handoff(self):
        await self.uncertain()
        self.playback.snapshots = "ok"
        self.playback.data = song("Y")
        async with self.runtime.lock:
            result = await self.device(self.first).pause(PLAYER)
        self.assertTrue(result["verified"])
        self.playback.data = song("X")  # later external playback must not revive evidence
        await self.close(self.first)
        await self.close(self.second)
        self.assert_pauses(1)

    async def test_invalid_item_does_not_disturb_existing_cleanup(self):
        await self.play(self.first, "X")
        async with self.runtime.lock:
            with self.assertRaises(DemoError):
                await self.device(self.second).change("play_item", {"player": PLAYER, "item": "bad"})
        self.assert_owner(self.first, "X")
        await self.close(self.first)
        self.assert_pauses(1)

    async def test_refused_handoff_removes_new_resolvers_losing_claim(self):
        await self.play(self.first, "X", service="svc1")
        self.device(self.second).mp2.send = "refuse"
        with self.assertRaises(DemoError):
            await self.play(self.second, "Y", service="svc2")
        self.assert_owner(self.first, "X")
        self.assertNotIn(PLAYER, self.device(self.second).owned)

    async def test_delayed_handoff_removes_old_resolvers_losing_claim(self):
        await self.play(self.first, "X", service="svc1")
        self.device(self.second).mp2.send = "refuse"
        self.playback.snapshots = "error"
        with self.assertRaises(DemoError):
            await self.play(self.second, "Y", service="svc2")
        self.playback.snapshots = "ok"
        self.playback.data = song("Y", service="svc2")
        async with self.runtime.lock:
            await self.device(self.first)._resolve_handoff(PLAYER)
        self.assert_owner(self.second, "Y")
        self.assertNotIn(PLAYER, self.device(self.first).owned)

    async def failed_skip_after_handoff(self, action, delayed_intended=False):
        original = ControlledMp2.action

        async def dispatch(client, player, action_id, options=None):
            if action_id in ("NextTrack", "PreviousTrack"):
                client.playback.actions.append((client, action_id))
                raise DemoError("Skip dispatch failed")
            return await original(client, player, action_id, options)

        # Patch before either native _mp2() instruments and captures action.
        with patch.object(ControlledMp2, "action", dispatch):
            await self.play(self.first, "X", service="svc1")
            self.device(self.second).mp2.send = "refuse"
            if delayed_intended:
                self.playback.snapshots = "error"
            with self.assertRaises(DemoError):
                await self.play(self.second, "Y", service="svc2")
            self.playback.snapshots = "ok"
            if delayed_intended:
                self.playback.data = song("Y", service="svc2")
            claimant = self.first if delayed_intended else self.second
            winner = self.second if delayed_intended else self.first
            async with self.runtime.lock:
                with self.assertRaisesRegex(DemoError, "Skip dispatch failed"):
                    await self.device(claimant).change(
                        "player_action", {"player": PLAYER, "action": action}
                    )
            await self.close(winner)
            self.assert_pauses(0)
            await self.close(claimant)
            self.assertEqual(self.playback.data["PlayerState"], "paused")
            self.assert_pauses(1)
            self.assertEqual(identity(self.playback.data), {
                "name": "Y" if delayed_intended else "X", "profile": "p1",
                "service": "svc2" if delayed_intended else "svc1",
            })

    async def test_failed_next_after_refused_handoff_keeps_cleanup(self):
        await self.failed_skip_after_handoff("next")

    async def test_failed_previous_after_refused_handoff_keeps_cleanup(self):
        await self.failed_skip_after_handoff("previous")

    async def test_failed_next_after_delayed_intended_handoff_keeps_cleanup(self):
        await self.failed_skip_after_handoff("next", delayed_intended=True)

    async def test_failed_previous_after_delayed_intended_handoff_keeps_cleanup(self):
        await self.failed_skip_after_handoff("previous", delayed_intended=True)


if __name__ == "__main__":
    unittest.main()
