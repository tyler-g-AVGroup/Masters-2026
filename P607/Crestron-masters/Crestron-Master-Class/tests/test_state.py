"""State handling uses the nesting and deltas shown in Crestron's examples."""

import unittest

from crestron.state import PlayerState, parse_messages


class StateTests(unittest.TestCase):
    def test_multiple_documents_in_one_websocket_frame(self):
        messages = list(
            parse_messages('{"Device": {}}\n {"Device": {"SubscriptionMgr": {}}}')
        )
        self.assertEqual(len(messages), 2)

    def test_delta_merge_trimmed_title_and_estimated_position(self):
        now = [100.0]
        state = PlayerState(clock=lambda: now[0])
        state.update(
            {
                "PlayerState": "playing",
                "AvailableActions": ["Pause"],
                "Player": {
                    "NowPlayingData": {
                        "TrackTitle": " ",
                        "StationName": " Song ",
                        "ArtistName": " Artist ",
                        "Duration": 200,
                        "ElapsedSec": 0,
                    }
                },
            }
        )
        now[0] += 10
        state.update({"AvailableActions": {}, "Player": {"Shuffle": True}})
        self.assertEqual(state.metadata()["title"], "Song")
        self.assertEqual(state.metadata()["artist"], "Artist")
        self.assertEqual(state.metadata()["position"], 10)
        self.assertEqual(state.data["AvailableActions"], ["Pause"])
        state.update({"Player": {"NowPlayingData": {"ElapsedSec": 80}}})
        now[0] += 2
        self.assertEqual(state.metadata()["position"], 82)

    def test_polled_zero_does_not_reset_progress_and_pause_freezes_it(self):
        now = [100.0]
        state = PlayerState(clock=lambda: now[0])
        state.update(
            {"PlayerState": "playing", "Player": {"NowPlayingData": {"ElapsedSec": 0}}}
        )
        now[0] += 10
        state.update({"Player": {"NowPlayingData": {"ElapsedSec": 0}}}, pushed=False)
        self.assertEqual(state.elapsed(), 10)
        state.update({"PlayerState": "paused"})
        now[0] += 15
        self.assertEqual(state.elapsed(), 10)

    def test_unknown_duration_does_not_clamp_and_known_duration_does(self):
        state = PlayerState(clock=lambda: 100)
        state.update({"Player": {"NowPlayingData": {"Duration": -1, "ElapsedSec": 50}}})
        self.assertEqual(state.elapsed(), 50)
        state.update({"Player": {"NowPlayingData": {"Duration": 40}}})
        self.assertEqual(state.elapsed(), 40)

    def test_new_track_state_change_resets_position_unless_position_is_explicit(self):
        now = [100.0]
        state = PlayerState(clock=lambda: now[0])
        state.update(
            {
                "PlayerState": "paused",
                "Player": {
                    "NowPlayingData": {"TrackTitle": "Old song", "ElapsedSec": 70}
                },
            }
        )
        state.update(
            {
                "PlayerState": "playing",
                "Player": {"NowPlayingData": {"TrackTitle": "New song"}},
            }
        )
        self.assertEqual(state.elapsed(), 0)

        explicit = PlayerState(clock=lambda: now[0])
        explicit.update(
            {
                "PlayerState": "paused",
                "Player": {
                    "NowPlayingData": {"TrackTitle": "Old song", "ElapsedSec": 70}
                },
            }
        )
        explicit.update(
            {
                "PlayerState": "playing",
                "Player": {
                    "NowPlayingData": {"TrackTitle": "New song", "ElapsedSec": 3}
                },
            }
        )
        self.assertEqual(explicit.elapsed(), 3)

    def test_live_station_retitle_keeps_the_timer(self):
        clock = [100.0]
        state = PlayerState(clock=lambda: clock[0])
        state.update(
            {
                "PlayerState": "playing",
                "Player": {
                    "NowPlayingData": {
                        "TrackTitle": "SWR3",
                        "StationName": "SWR3",
                        "Duration": 0,
                        "ElapsedSec": 0,
                    }
                },
            }
        )
        clock[0] += 20
        state.update({"Player": {"NowPlayingData": {"TrackTitle": "Morning show"}}})
        self.assertAlmostEqual(state.metadata()["position"], 20, delta=0.5)
        self.assertEqual(state.metadata()["duration"], 0)
        self.assertEqual(PlayerState().metadata()["duration"], -1)  # missing = unknown
