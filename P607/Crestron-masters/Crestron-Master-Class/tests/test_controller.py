"""Failure cases that must not replay a load or resume at another volume."""

import unittest
from unittest.mock import AsyncMock

from crestron.config import Config
from crestron.controller import Controller
from crestron.errors import DemoError
from crestron.state import PlayerState


def menu(items, total=None, parent=None):
    """One ProviderBrowseMenu page."""
    return {
        "ParentBrowseKey": parent or {},
        "Categories": {
            "Item01": {
                "ItemCount": len(items),
                "TotalItemCount": len(items) if total is None else total,
                "MenuDataItems": items,
            }
        },
    }


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    def controller(self):
        config = Config("example.invalid", "client", "c2VjcmV0", "admin", "password")
        controller = Controller(config)
        controller.plan = {
            "track": {"title": "Song"},
            "profile": {"key": "Profile1"},
            "service": {"key": "Provider10"},
            "zone": {"key": "Zone1", "name": "Room"},
        }
        controller.owned_playback = True
        controller.volume = 20
        controller.mp2.players["Player01"] = PlayerState()
        controller._recheck_zone = AsyncMock()
        controller.mp2.close = AsyncMock()
        controller.rest.close = AsyncMock()
        return controller

    async def test_cleanup_reconciles_applied_load_when_cached_state_is_stopped(self):
        controller = self.controller()
        state = controller.mp2.players["Player01"]
        state.update(
            {
                "PlayerState": "stopped",
                "Player": {"NowPlayingData": {"StationName": " "}},
            }
        )

        async def fresh_snapshot(path):
            delta = {
                "PlayerState": "playing",
                "AvailableActions": ["Pause"],
                "Player": {"NowPlayingData": {"StationName": "Song"}},
            }
            state.update(delta, pushed=False)
            return delta

        async def paused(*args, **kwargs):
            state.update({"PlayerState": "paused"})
            return state.metadata()

        controller.mp2.get = AsyncMock(side_effect=fresh_snapshot)
        controller.mp2.action = AsyncMock(return_value=10)
        controller.mp2.wait_player = AsyncMock(side_effect=paused)
        await controller.close()
        controller.mp2.action.assert_awaited_once_with("Player01", "Pause")
        self.assertEqual(state.data["PlayerState"], "paused")
        controller.mp2.close.assert_awaited_once()
        controller.rest.close.assert_awaited_once()

    async def test_resume_refuses_volume_changed_after_verified_write(self):
        controller = self.controller()
        state = controller.mp2.players["Player01"]
        delta = {
            "PlayerState": "paused",
            "AvailableActions": ["Play"],
            "Player": {"NowPlayingData": {"StationName": "Song"}},
        }
        state.update(delta)
        controller.mp2.get = AsyncMock(return_value=delta)
        controller.mp2.action = AsyncMock()

        async def external_volume_change(*args, **kwargs):
            controller.volume = 30

        controller._recheck_zone = AsyncMock(side_effect=external_volume_change)
        with self.assertRaisesRegex(DemoError, "refusing to resume"):
            await controller.play()
        controller.mp2.action.assert_not_awaited()

    async def test_final_pause_returns_actual_volume_instead_of_cached_ten(self):
        controller = self.controller()
        controller.volume = 10
        state = controller.mp2.players["Player01"]
        delta = {
            "PlayerState": "paused",
            "AvailableActions": ["Play"],
            "Player": {"NowPlayingData": {"StationName": "Song"}},
        }
        state.update(delta)
        controller.mp2.get = AsyncMock(return_value=delta)

        async def actual_volume(*args, **kwargs):
            controller.volume = 15

        controller._recheck_zone = AsyncMock(side_effect=actual_volume)
        result = await controller.pause()
        self.assertEqual(result["volume"], 15)

    async def test_first_song_on_second_provider_root_page_uses_signed_parent(self):
        controller = self.controller()
        stations = [
            {
                "BrowseKey": "station-{}".format(index),
                "BrowseItemName": "Station {}".format(index),
                "StreamingMediaType": "station",
            }
            for index in range(20)
        ]
        signed_parent = {
            "BrowseKey": "Provider10",
            "SignedData": {
                "SourceData": {"Page": {"limit": 20}, "opaque": "preserve-me"},
                "signature": "provider-signature",
            },
        }
        song = {
            "BrowseKey": "first-song",
            "BrowseItemName": "First Song",
            "StreamingMediaType": "song",
            "SignedData": {"signature": "song-signature"},
        }

        def page(items):
            return {
                "ParentBrowseKey": signed_parent,
                "Categories": {
                    "Tracks": {
                        "ItemCount": len(items),
                        "TotalItemCount": 21,
                        "MenuDataItems": items,
                    }
                },
            }

        controller.mp2.browse = AsyncMock(side_effect=[page(stations), page([song])])
        result = await controller._first_track("Profile1", "Provider10")
        self.assertEqual(result, dict(song, browse_path=["First Song"]))
        calls = controller.mp2.browse.await_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].args, ("Profile1", "Provider10", None, 0))
        self.assertEqual(calls[1].args, ("Profile1", "Provider10", signed_parent, 20))
        self.assertIs(calls[1].args[2], signed_parent)

    async def test_page_of_null_entries_does_not_hide_the_song_on_the_next_page(self):
        controller = self.controller()
        parent = {
            "BrowseKey": "folder",
            "SignedData": {"SourceData": {"Page": {"limit": 20}}, "signature": "x"},
        }
        song = {
            "BrowseKey": "song-1",
            "BrowseItemName": "Song 1",
            "StreamingMediaType": "song",
            "SignedData": {"signature": "song-signature"},
        }

        def page(items, count):
            return {
                "ParentBrowseKey": parent,
                "Categories": {
                    "Tracks": {
                        "ItemCount": count,
                        "TotalItemCount": 21,
                        "MenuDataItems": items,
                    }
                },
            }

        controller.mp2.browse = AsyncMock(
            side_effect=[page([None] * 20, 20), page([song], 1)]
        )
        result = await controller._first_track("Profile1", "Provider10")
        self.assertEqual(result["BrowseKey"], "song-1")
        self.assertEqual(controller.mp2.browse.await_count, 2)

    async def test_device_that_ignores_the_offset_still_terminates(self):
        controller = self.controller()
        folder = {
            "BrowseKey": "folder",
            "BrowseItemName": "Folder",
            "StreamingMediaType": "dirmenu",
            "SignedData": {"signature": "x"},
        }
        parent = {
            "BrowseKey": "Provider10",
            "SignedData": {"SourceData": {"Page": {"limit": 20}}, "signature": "x"},
        }
        repeated = {
            "ParentBrowseKey": parent,
            "Categories": {
                "Items": {
                    "ItemCount": 1,
                    "TotalItemCount": 41,
                    "MenuDataItems": [folder],
                }
            },
        }
        empty = {"ParentBrowseKey": {}, "Categories": {}}
        controller.mp2.browse = AsyncMock(
            side_effect=lambda profile, provider, item, offset: (
                empty if item else repeated
            )
        )
        with self.assertRaises(DemoError):
            await controller._first_track("Profile1", "Provider10")
        self.assertLess(controller.mp2.browse.await_count, 10)

    async def test_repeating_folder_does_not_use_up_the_budget_for_later_folders(self):
        controller = self.controller()
        parent = {
            "BrowseKey": "Provider10",
            "SignedData": {"SourceData": {"Page": {"limit": 20}}, "signature": "x"},
        }

        def folder(key):
            return {
                "BrowseKey": key,
                "BrowseItemName": key,
                "StreamingMediaType": "dirmenu",
                "SignedData": {"signature": key},
            }

        stations = [
            {"BrowseKey": "station-{}".format(i), "StreamingMediaType": "station"}
            for i in range(20)
        ]
        song = {
            "BrowseKey": "song-1",
            "BrowseItemName": "Song 1",
            "StreamingMediaType": "song",
            "SignedData": {"signature": "s"},
        }

        def menu(items, total):
            return {
                "ParentBrowseKey": parent,
                "Categories": {
                    "Items": {
                        "ItemCount": len(items),
                        "TotalItemCount": total,
                        "MenuDataItems": items,
                    }
                },
            }

        async def browse(profile, provider, item, offset):
            key = item["BrowseKey"] if item else None
            if key is None or key == "Provider10":
                return menu([folder("loops"), folder("good")], 2)
            if key == "loops":  # ignores the offset and repeats one page forever
                return menu(stations, 1000)
            return menu([song], 1)

        controller.mp2.browse = browse
        result = await controller._first_track("Profile1", "Provider10")
        self.assertEqual(result["BrowseKey"], "song-1")

    async def test_named_service_is_used_without_sign_in_and_stations_play(self):
        config = Config(
            "example.invalid", "c", "c2VjcmV0", "a", "p", service="Internet Radio"
        )
        controller = Controller(config)
        profiles = {
            "Profile1": {
                "Name": "test",
                "AssignedProviders": {
                    "Provider10": {"Name": "TIDAL", "IsAuthenticated": False},
                    "Provider7": {"Name": "Internet Radio", "IsAuthenticated": False},
                },
            }
        }
        mp2 = {
            "/Device/MediaPlayerNeXt/Players": {"Player01": {"PlayerState": "stopped"}},
            "/Device/StreamingServices/UserProfiles": profiles,
        }
        rest = {
            "/Device/DeviceInfo": {"Device": {"DeviceInfo": {"Model": "NAX"}}},
            "/Device/InputSources": {
                "Device": {
                    "InputSources": {
                        "Inputs": {"Input05": {"AudioType": "MediaPlayer"}}
                    }
                }
            },
            "/Device/ZoneOutputs": {
                "Device": {
                    "ZoneOutputs": {
                        "Version": "2.0.31",
                        "Zones": {
                            "Zone1": {
                                "Name": "Room",
                                "IsBussed": False,
                                "ZoneBasedProviders": {"ReservedPlayer": "Input05"},
                                "ZoneAudio": {
                                    "Volume": 300,
                                    "MinVolume": 0,
                                    "MaxVolume": 1000,
                                    "IsMuted": False,
                                },
                            }
                        },
                    }
                }
            },
            "/Device/AvMatrixRouting": {"Device": {"AvMatrixRouting": {"Routes": {}}}},
        }
        controller.mp2.open = AsyncMock()
        controller.mp2.subscribe = AsyncMock()
        controller.mp2.get = AsyncMock(side_effect=lambda path: mp2[path])
        controller.rest.get = AsyncMock(side_effect=lambda path: rest[path])
        station = {
            "BrowseKey": "/id/radio/1",
            "BrowseItemName": "SWR3",
            "StreamingMediaType": "station",
            "SignedData": "opaque",
        }
        controller.mp2.browse = AsyncMock(return_value=menu([station]))
        plan = await controller.prepare()
        self.assertEqual(plan["service"]["key"], "Provider7")
        self.assertEqual(plan["track"]["title"], "SWR3")
        self.assertEqual(plan["track"]["kind"], "station")

    async def test_unknown_named_service_is_refused(self):
        config = Config("example.invalid", "c", "c2VjcmV0", "a", "p", service="Nope")
        controller = Controller(config)
        controller.mp2.open = AsyncMock()
        controller.mp2.subscribe = AsyncMock()
        controller.mp2.get = AsyncMock(
            side_effect=lambda path: (
                {"Player01": {"PlayerState": "stopped"}}
                if path.endswith("Players")
                else {
                    "Profile1": {
                        "AssignedProviders": {"Provider7": {"Name": "Internet Radio"}}
                    }
                }
            )
        )
        with self.assertRaisesRegex(DemoError, "Nope"):
            await controller.prepare()

    def test_station_ownership_follows_the_station_name_not_the_program(self):
        controller = self.controller()
        controller.plan["track"] = {"title": "SWR3", "kind": "station"}
        controller.plan["service"] = {"key": "Provider7"}
        state = controller.mp2.players["Player01"]
        state.update(
            {
                "PlayerState": "playing",
                "Player": {
                    "ProviderKey": "Provider7",
                    "NowPlayingData": {
                        "TrackTitle": "Morning show",
                        "StationName": "SWR3",
                        "Duration": 0,
                    },
                },
            }
        )
        controller._check_owner()  # program title changed; same station: still ours
        state.update({"Player": {"NowPlayingData": {"StationName": "Other FM"}}})
        with self.assertRaises(DemoError):
            controller._check_owner()

    async def test_named_folder_is_the_only_one_searched(self):
        controller = self.controller()
        controller.config.folder = "Popular stations"
        history = {
            "BrowseKey": "h",
            "BrowseItemName": "History",
            "StreamingMediaType": "dirmenu",
            "SignedData": "x",
        }
        popular = {
            "BrowseKey": "p",
            "BrowseItemName": "Popular stations",
            "StreamingMediaType": "dirmenu",
            "SignedData": "y",
        }
        station = {
            "BrowseKey": "s",
            "BrowseItemName": "SWR3",
            "StreamingMediaType": "station",
            "SignedData": "z",
        }
        opened = []

        async def browse(profile, provider, item, offset):
            opened.append(item["BrowseKey"] if item else "root")
            if item is None:
                return menu([history, popular])
            if item["BrowseKey"] == "h":
                raise DemoError("History must not be opened")
            return menu([station])

        controller.mp2.browse = browse
        result = await controller._first_track("Profile1", "Provider7")
        self.assertEqual(result["browse_path"], ["Popular stations", "SWR3"])
        self.assertEqual(opened, ["root", "p"])

        controller.config.folder = "Nope"
        with self.assertRaisesRegex(DemoError, "History, Popular stations"):
            await controller._first_track("Profile1", "Provider7")

    def test_song_ownership_stays_strict(self):
        controller = self.controller()  # planned song title is "Song"
        state = controller.mp2.players["Player01"]
        state.update(
            {
                "PlayerState": "playing",
                "Player": {
                    "NowPlayingData": {
                        "TrackTitle": "Next Song",
                        "StationName": "Song",
                        "Duration": 200,
                    }
                },
            }
        )
        with self.assertRaises(DemoError):  # StationName only counts for live radio
            controller._check_owner()

    async def test_named_folder_must_be_a_folder(self):
        controller = self.controller()
        controller.config.folder = "SWR3"
        station = {
            "BrowseKey": "s",
            "BrowseItemName": "SWR3",
            "StreamingMediaType": "station",
            "SignedData": "z",
        }
        controller.mp2.browse = AsyncMock(return_value=menu([station]))
        with self.assertRaisesRegex(DemoError, "not a folder"):
            await controller._first_track("Profile1", "Provider7")
