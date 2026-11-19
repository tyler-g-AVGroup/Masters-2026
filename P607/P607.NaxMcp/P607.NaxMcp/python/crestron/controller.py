"""The direct demo's discovery and verified steps; it never routes or unmutes on its own."""

import asyncio
import time

from .errors import DemoError
from .mp2 import Mp2Client
from .rest import RestClient, check_zone_version
from .state import at_path, same_item, text

PLAYABLE = ("song", "station", "podcastepisode")
FOLDERS = ("dirmenu", "album", "artist", "playlist", "podcastseries")


def menu_items(menu):
    for category in menu.get("Categories", {}).values():
        if not isinstance(category, dict):
            continue
        items = category.get("MenuDataItems", [])
        if isinstance(items, dict):
            items = [items] if "BrowseKey" in items else list(items.values())
        for item in items or []:
            if isinstance(item, dict) and item.get("BrowseKey"):
                yield item


class Controller:
    def __init__(self, config):
        self.config = config
        self.mp2 = Mp2Client(config)
        self.rest = RestClient(config)
        self.plan = None
        self.track = None
        self.input_key = None
        self.owned_playback = False
        self.volume = None
        self.lock = asyncio.Lock()

    async def prepare(self):
        await self.mp2.open()
        players = await self.mp2.get("/Device/MediaPlayerNeXt/Players")
        player = players.get(self.config.player)
        if not player or player.get("PlayerState") == "ready":
            raise DemoError(
                "{} is not an active device player.".format(self.config.player)
            )
        if player.get("PlayerState") not in ("paused", "stopped"):
            raise DemoError(
                "{} is already in use; pause it before starting this demo.".format(
                    self.config.player
                )
            )
        await self.mp2.subscribe(self.config.player)
        profiles = await self.mp2.get("/Device/StreamingServices/UserProfiles")
        if not profiles:
            raise DemoError("The device has no user profiles.")
        profile_key = next(iter(profiles))
        profile = profiles[profile_key]
        providers = profile.get("AssignedProviders", {})
        # A named service (key or name) is used as is: Internet Radio needs no sign-in.
        wanted = (self.config.service or "").casefold()
        chosen = [
            (key, value)
            for key, value in providers.items()
            if (
                wanted in (key.casefold(), text(value.get("Name")).casefold())
                if wanted
                else value.get("IsAuthenticated") is True
            )
        ]
        if not chosen:
            raise DemoError(
                "Service '{}' is not assigned to the first profile.".format(
                    self.config.service
                )
                if wanted
                else "The first profile has no signed-in streaming service; set service in config.json."
            )
        provider_key, provider = chosen[0]

        info = (
            at_path(await self.rest.get("/Device/DeviceInfo"), "/Device/DeviceInfo")
            or {}
        )
        inputs = (
            at_path(
                await self.rest.get("/Device/InputSources"),
                "/Device/InputSources/Inputs",
            )
            or {}
        )
        media_inputs = [
            key
            for key, value in inputs.items()
            if value.get("AudioType") == "MediaPlayer"
        ]
        if self.config.player_input:
            self.input_key = self.config.player_input
            if self.input_key not in media_inputs:
                raise DemoError("player_input is not a reported MediaPlayer input.")
        elif self.config.player == "Player01" and media_inputs:
            self.input_key = media_inputs[0]
        else:
            raise DemoError(
                "Set player_input to the confirmed input mapping for this player."
            )
        zones_obj = (
            at_path(await self.rest.get("/Device/ZoneOutputs"), "/Device/ZoneOutputs")
            or {}
        )
        check_zone_version(zones_obj.get("Version", "0"))
        zones = zones_obj.get("Zones", {})
        candidates = [
            key
            for key, value in zones.items()
            if value.get("ZoneBasedProviders", {}).get("ReservedPlayer")
            == self.input_key
        ]
        zone_key = self.config.zone
        if not zone_key:
            if len(candidates) != 1:
                raise DemoError(
                    "Player-to-zone mapping is ambiguous; set zone in config.json."
                )
            zone_key = candidates[0]
        if zone_key not in candidates:
            raise DemoError(
                "Configured zone does not reserve the selected player's input."
            )
        zone = zones[zone_key]
        self._validate_zone(zone)
        routes = (
            at_path(
                await self.rest.get("/Device/AvMatrixRouting"),
                "/Device/AvMatrixRouting/Routes",
            )
            or {}
        )
        affected = [
            key
            for key, route in routes.items()
            if route.get("AudioSource") == self.input_key
        ]
        if any(key != zone_key for key in affected):
            raise DemoError(
                "Another zone also routes this player's input; use an isolated player for the demo."
            )
        if zone.get("IsSignalDetected"):
            raise DemoError(
                "The selected zone reports an active signal; it is not idle."
            )
        self.volume = zone["ZoneAudio"]["Volume"] / 10.0
        self.track = await self._first_track(profile_key, provider_key)
        track_meta = self.track.get("MediaTypeMetaData", {})
        self.plan = {
            "profile": {"key": profile_key, "name": text(profile.get("Name"))},
            "service": {"key": provider_key, "name": text(provider.get("Name"))},
            "player": self.config.player,
            "zone": {"key": zone_key, "name": text(zone.get("Name"))},
            "input": self.input_key,
            "track": {
                "title": text(self.track.get("BrowseItemName")),
                "kind": text(self.track.get("StreamingMediaType")).lower(),
                "artist": text(track_meta.get("ArtistName")),
                "album": text(track_meta.get("AlbumName")),
                "browse_path": self.track["browse_path"],
            },
            "initial_volume": self.volume,
            "initial_seconds": self.config.initial_seconds,
            "resume_seconds": self.config.resume_seconds,
            "affected_zones": [{"key": key} for key in affected],
            "routed": zone_key in affected,
            "device": {
                "model": info.get("Model", "unknown"),
                "firmware": info.get("DeviceVersion", "unknown"),
            },
        }
        return self.plan

    def _validate_zone(self, zone):
        audio = zone.get("ZoneAudio", {})
        if zone.get("IsBussed") is not False:
            raise DemoError("This demo requires an independent, unbussed zone.")
        for key in ("Volume", "MinVolume", "MaxVolume"):
            if type(audio.get(key)) is not int:
                raise DemoError(
                    "Zone did not report {}; refusing to guess its volume limits.".format(
                        key
                    )
                )
        if not audio["MinVolume"] <= 100 <= audio["MaxVolume"]:
            raise DemoError("10% is outside the selected zone's volume limits.")
        if audio.get("IsMuted") is not False:
            raise DemoError("Zone is muted; this demo will not unmute it implicitly.")

    async def _first_track(self, profile, provider):
        visited = set()
        requests = 0
        deadline = time.monotonic() + 120

        async def visit(item, path, depth):
            nonlocal requests
            if depth > 8 or requests >= 40 or time.monotonic() > deadline:
                raise DemoError(
                    "No song or station found within the demo's browse limits (8 levels, 40 pages, 120 seconds)."
                )
            key = item["BrowseKey"] if item else provider
            if key in visited:
                return None
            visited.add(key)
            offset = 0
            page_item = item
            seen_items = set()
            while requests < 40 and time.monotonic() < deadline:
                menu = await self.mp2.browse(profile, provider, page_item, offset)
                requests += 1
                fresh = repeated = False
                for child in menu_items(menu):
                    child_key = child["BrowseKey"]
                    if child_key in seen_items:
                        repeated = True
                        continue
                    seen_items.add(child_key)
                    fresh = True
                    child_path = path + [text(child.get("BrowseItemName"))]
                    kind = text(child.get("StreamingMediaType")).lower()
                    if kind in PLAYABLE and child.get("SignedData"):
                        result = dict(child)
                        result["browse_path"] = child_path
                        return result
                    if kind in FOLDERS and child.get("SignedData"):
                        result = await visit(child, child_path, depth + 1)
                        if result:
                            return result
                parent = menu.get("ParentBrowseKey", {})
                categories = [
                    value
                    for value in menu.get("Categories", {}).values()
                    if isinstance(value, dict)
                ]
                count = sum(value.get("ItemCount", 0) for value in categories)
                total = sum(value.get("TotalItemCount", 0) for value in categories)
                # A page of only seen items means the device ignores the offset: stop.
                # A page of only null entries is not that: count raw entries and go on.
                if (
                    (repeated and not fresh)
                    or count <= 0
                    or offset + count >= total
                    or not parent.get("SignedData")
                ):
                    return None
                page = parent["SignedData"].get("SourceData", {}).get("Page", {})
                offset += page.get("limit", count) or count or 20
                page_item = parent
            raise DemoError("No song or station found within the demo's browse limits.")

        start, path = None, []
        if self.config.folder:
            # Search one named top-level folder only (for example "Popular stations").
            root = list(menu_items(await self.mp2.browse(profile, provider, None, 0)))
            requests += 1
            names = [text(item.get("BrowseItemName")) for item in root]
            folded = [name.casefold() for name in names]
            if self.config.folder.casefold() not in folded:
                raise DemoError(
                    "Folder '{}' was not found; this service offers: {}".format(
                        self.config.folder, ", ".join(names)
                    )
                )
            index = folded.index(self.config.folder.casefold())
            start, path = root[index], [names[index]]
            kind = text(start.get("StreamingMediaType")).lower()
            if kind not in FOLDERS or not start.get("SignedData"):
                raise DemoError(
                    "'{}' is not a folder that can be opened.".format(
                        self.config.folder
                    )
                )
        result = await visit(start, path, 1 if start else 0)
        if not result:
            raise DemoError(
                "The selected service contains no browsable song or station; no other service was selected."
            )
        return result

    def _require_plan(self):
        if not self.plan:
            raise DemoError("Prepare the demo before reading or changing its player.")
        if self.mp2.failure:
            raise self.mp2.failure

    async def snapshot(self):
        self._require_plan()
        status = self.mp2.players[self.config.player].metadata()
        status.update(
            {
                "volume": self.volume,
                "player": self.config.player,
                "zone": self.plan["zone"],
                "verified": True,
            }
        )
        return status

    async def _recheck_zone(self, check_initial=False):
        zone_key = self.plan["zone"]["key"]
        path = "/Device/ZoneOutputs/Zones/" + zone_key
        zone = at_path(await self.rest.get(path), path) or {}
        self._validate_zone(zone)
        if zone.get("ZoneBasedProviders", {}).get("ReservedPlayer") != self.input_key:
            raise DemoError(
                "Player-to-zone mapping changed after preparation; prepare again."
            )
        routes = (
            at_path(
                await self.rest.get("/Device/AvMatrixRouting"),
                "/Device/AvMatrixRouting/Routes",
            )
            or {}
        )
        affected = [
            key
            for key, route in routes.items()
            if route.get("AudioSource") == self.input_key
        ]
        if affected != [zone["key"] for zone in self.plan["affected_zones"]]:
            raise DemoError("Player routing changed after preparation; prepare again.")
        self.volume = zone["ZoneAudio"]["Volume"] / 10.0
        if check_initial and self.volume != self.plan["initial_volume"]:
            raise DemoError("Zone volume changed after preparation; prepare again.")

    def _check_owner(self):
        state = self.mp2.players[self.config.player]
        player = state.data.get("Player", {})
        # Songs carry their name in TrackTitle or (TIDAL) StationName; live radio
        # retitles TrackTitle per programme but keeps StationName. Either may match.
        if not same_item(player.get("NowPlayingData", {}), self.plan["track"]["title"]):
            raise DemoError(
                "The player changed tracks; refusing to control another playback session."
            )
        for field, key in (("ProfileKey", "profile"), ("ProviderKey", "service")):
            if player.get(field) and player[field] != self.plan[key]["key"]:
                raise DemoError(
                    "The player's profile or service changed; refusing to control another session."
                )

    async def load_track(self):
        async with self.lock:
            self._require_plan()
            await self._recheck_zone(check_initial=True)
            state = await self.mp2.fresh_player(self.config.player)
            if state.data.get("PlayerState") not in ("paused", "stopped"):
                raise DemoError(
                    "Player started playing after preparation; prepare again."
                )
            # A timeout does not prove LoadSource had no effect.
            self.owned_playback = True
            baseline = await self.mp2.load_source(
                self.config.player,
                self.plan["profile"]["key"],
                self.plan["service"]["key"],
                self.track["SignedData"],
            )
            await self.mp2.wait_player(
                self.config.player,
                baseline,
                "playing",
                self.plan["track"]["title"],
                timeout=15,
            )
            return await self.snapshot()

    async def _transport(self, action, expected):
        self._require_plan()
        if not self.owned_playback:
            raise DemoError(
                "This run has not loaded a track; refusing an unrelated playback change."
            )
        # A timed-out LoadSource can have applied even when its push was lost.
        # Reconcile live state before cleanup instead of trusting the old title.
        state = await self.mp2.fresh_player(self.config.player)
        if action == "Pause" and state.data.get("PlayerState") == "stopped":
            return await self.snapshot()
        self._check_owner()
        deadline = time.monotonic() + 2
        while (
            action not in state.data.get("AvailableActions", [])
            and time.monotonic() < deadline
        ):
            # State and AvailableActions may arrive in separate pushes.
            if state.data.get("PlayerState") == expected:
                break
            await asyncio.sleep(0.1)
        if action not in state.data.get("AvailableActions", []):
            if state.data.get("PlayerState") == expected:
                return await self.snapshot()
            raise DemoError(
                "{} is not available for the current player state.".format(action)
            )
        if action == "Play":
            await self._recheck_zone()
            if self.volume != 10.0:
                raise DemoError(
                    "Zone volume changed after the 10% write; refusing to resume at another level."
                )
        baseline = await self.mp2.action(self.config.player, action)
        await self.mp2.wait_player(self.config.player, baseline, expected)
        return await self.snapshot()

    async def pause(self):
        async with self.lock:
            status = await self._transport("Pause", "paused")
            await self._recheck_zone()
            status["volume"] = self.volume
            return status

    async def play(self):
        async with self.lock:
            return await self._transport("Play", "playing")

    async def set_volume(self, percent):
        async with self.lock:
            self._require_plan()
            if type(percent) is not int or percent != 10:
                raise DemoError("This demo sets only the requested 10% volume.")
            await self.mp2.fresh_player(self.config.player)
            self._check_owner()
            if self.mp2.players[self.config.player].data.get("PlayerState") != "paused":
                raise DemoError("Pause the demo track before setting volume.")
            await self._recheck_zone()
            # REST volume is in tenths of a percent: 100 = 10%.
            await self.rest.set_audio(self.plan["zone"]["key"], "Volume", 100)
            self.volume = 10.0
            return await self.snapshot()

    async def close(self):
        errors = []
        if self.owned_playback and self.plan:
            try:
                state = await self.mp2.fresh_player(self.config.player)
                if state.data.get("PlayerState") not in ("paused", "stopped"):
                    await self.pause()
            except Exception as exc:
                errors.append("cleanup pause: {}".format(exc))
        for client in (self.mp2, self.rest):
            try:
                await client.close()
            except Exception as exc:
                errors.append("connection cleanup: {}".format(exc))
        if errors:
            raise DemoError("; ".join(errors))
