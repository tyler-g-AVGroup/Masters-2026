"""General device access for the MCP tools: reads, previews and verified changes.

The MCP client holds the user's choices (profile, service, item, player, zone);
this class holds the connections and the SignedData behind short item ids.
"""

import asyncio
import json
import time
from collections import OrderedDict

from .controller import FOLDERS, PLAYABLE, menu_items
from .errors import DemoError
from .mp2 import Mp2Client
from .rest import RestClient, check_zone_version
from .state import at_path, identity, is_live, same_item, same_source, text, title_of

SEARCH_CATEGORIES = ("song", "album", "artist", "playlist", "station")
ACTIONS = {  # tool action -> MP2 ActionId
    "play": "Play",
    "next": "NextTrack",
    "previous": "PreviousTrack",
    "seek": "Seek",
    "forward": "Ffwd",
    "rewind": "Rewind",
    "shuffle": "Shuffle",
    "repeat": "Repeat",
}
UNLISTED = {"shuffle", "repeat"}  # work even when not in AvailableActions (skill notes)
SKIPS = ("next", "previous")
REPEAT = {"off": 0, "track": 1, "list": 2}
MAX_IDS = 2000


def percent(units):
    # REST volume units are tenths of a percent.
    return units / 10.0 if isinstance(units, (int, float)) else None


def now_playing(delta):
    return (delta.get("Player") or {}).get("NowPlayingData") or {}


class Device:
    def __init__(self, config):
        self.config = config
        self.mp2 = None
        self.rest = RestClient(config)
        self.ids = OrderedDict()
        self.counter = 0
        self.owned = {}  # player -> identity() of what this server started
        self.subscribed = set()
        self.opened_at = 0.0
        self.connecting = asyncio.Lock()  # tools/list reads run beside the tool calls
        self.player_slots = set()  # every player id the device lists, used or not
        self.zone_names = None  # {zone id: name} as last read
        self.profile_names = None  # {profile id: name} as last read

    # --- connections -------------------------------------------------------

    async def _mp2(self):
        if self.mp2 and not self.mp2.failure:
            return self.mp2
        async with self.connecting:  # one connect at a time, even from tools/list
            if self.mp2 and not self.mp2.failure:
                return self.mp2
            if self.mp2:  # dropped
                await self.mp2.close()
                self.mp2 = None
            wait = self.opened_at + 10 - time.monotonic()
            if self.opened_at and wait > 0:  # never open connections faster than every 10 s
                raise DemoError(
                    "MP2 connection is not available; retry in {:.0f} seconds.".format(wait)
                )
            self.opened_at = time.monotonic()
            client = Mp2Client(self.config)
            try:
                await client.open()
                players = await client.get("/Device/MediaPlayerNeXt/Players") or {}
                active = [
                    key
                    for key, value in players.items()
                    if isinstance(value, dict) and value.get("PlayerState") != "ready"
                ]
                await client.subscribe(*active, favorites=True)
            except BaseException:
                await client.close()
                raise
            self.mp2, self.subscribed = client, set(active)
            self.player_slots = set(players)
            return client

    async def close(self):
        """Pause what this server started and is still playing; close connections.
        Returns the players it paused."""
        errors, paused = [], []
        for player, owned in list(self.owned.items()):
            if not self.mp2 or self.mp2.failure:
                errors.append(
                    "cleanup pause {}: MP2 connection lost; playback may still be active".format(player)
                )
                continue
            try:
                # Pause only what this server started, not someone else's later choice.
                if self._still_ours(await self._fresh_player(player), owned):
                    await self.pause(player)
                    paused.append(player)
            except Exception as exc:
                errors.append("cleanup pause {}: {}".format(player, exc))
        for client in (self.mp2, self.rest):
            if client is None:
                continue
            try:
                await client.close()
            except Exception as exc:
                errors.append("connection cleanup: {}".format(exc))
        self.mp2 = None
        if errors:
            raise DemoError("; ".join(errors))
        return paused

    @staticmethod
    def _still_ours(data, owned):
        now = identity(data)
        return (
            data.get("PlayerState") == "playing"
            and same_item(now_playing(data), owned["name"])
            and same_source(owned, now)
        )

    # --- ids ---------------------------------------------------------------

    def _remember(self, entry):
        self.counter += 1
        key = "i{}".format(self.counter)
        self.ids[key] = entry
        while len(self.ids) > MAX_IDS:
            self.ids.popitem(last=False)
        return key

    def _entry(self, item_id, kind):
        entry = self.ids.get(item_id) if isinstance(item_id, str) else None
        if not entry or entry["type"] != kind:
            raise DemoError(
                "Unknown or expired {} id '{}'; list again.".format(kind, item_id)
            )
        return entry

    def _summary(self, profile, service, item, section=None, register=True):
        kind = text(item.get("StreamingMediaType")).lower()
        meta = item.get("MediaTypeMetaData") or {}
        service = text(meta.get("ProviderKey")) or service
        signed = bool(item.get("SignedData"))
        summary = {
            "name": text(item.get("BrowseItemName")),
            "kind": kind,
            "playable": kind in PLAYABLE and signed,
            "folder": kind in FOLDERS and signed,
            "service": service,
            "artist": text(meta.get("ArtistName")),
            "album": text(meta.get("AlbumName")),
        }
        if section:
            summary["section"] = section
        if register and (summary["playable"] or summary["folder"]):
            summary["id"] = self._remember(
                {"type": "item", "profile": profile, "service": service, "item": item}
            )
        return summary

    def _listing(self, menu, profile, service, offset, paged=True):
        categories = [
            value
            for value in (menu.get("Categories") or {}).values()
            if isinstance(value, dict)
        ]
        items = [
            self._summary(profile, service, item, text(category.get("DisplayMenuName")) or None)
            for category in categories
            for item in menu_items({"Categories": {"x": category}})
        ]
        result = {"profile": profile, "service": service, "items": items}
        count = sum(value.get("ItemCount", 0) or 0 for value in categories)
        total = sum(value.get("TotalItemCount", 0) or 0 for value in categories)
        parent = menu.get("ParentBrowseKey") or {}
        signed = parent.get("SignedData")
        if paged and count > 0 and offset + count < total and isinstance(signed, dict):
            page = (signed.get("SourceData") or {}).get("Page") or {}
            result["next_page"] = self._remember(
                {
                    "type": "page",
                    "profile": profile,
                    "service": service,
                    "item": parent,
                    "offset": offset + (page.get("limit") or count),
                }
            )
        return result

    # --- reads -------------------------------------------------------------

    async def _profiles(self):
        mp2 = await self._mp2()
        profiles = await mp2.get("/Device/StreamingServices/UserProfiles")
        profiles = profiles if isinstance(profiles, dict) else {}
        self.profile_names = {
            key: text(value.get("Name")) for key, value in profiles.items() if isinstance(value, dict)
        }
        return profiles

    @staticmethod
    def _unknown(kind, key, names):
        """Refusal for an id the device does not list, naming the ones it does."""
        listed = ", ".join(
            "{} ({})".format(k, n) if n else k for k, n in sorted(names.items())
        )
        return DemoError("Unknown {} '{}'; {}s are: {}".format(kind, key, kind, listed or "none"))

    async def _check_profile(self, profile):
        """Fail at once on a profile id the device does not list: browsing one waits out the timeout."""
        if self.profile_names is None or profile not in self.profile_names:
            await self._profiles()  # also refreshes the list
        if profile not in self.profile_names:
            raise self._unknown("profile", profile, self.profile_names)

    async def profiles(self):
        profiles = await self._profiles()
        return {
            "profiles": [
                {
                    "profile": key,
                    "name": text(value.get("Name")),
                    "services": len(value.get("AssignedProviders") or {}),
                }
                for key, value in profiles.items()
                if isinstance(value, dict)
            ]
        }

    async def services(self, profile):
        profiles = await self._profiles()
        if profile not in profiles:
            raise self._unknown("profile", profile, self.profile_names)
        providers = profiles[profile].get("AssignedProviders") or {}
        return {
            "profile": profile,
            "services": [
                {
                    "service": key,
                    "name": text(value.get("Name")),
                    "signed_in": value.get("IsAuthenticated") is True,
                }
                for key, value in providers.items()
                if isinstance(value, dict)
            ],
        }

    async def browse(self, profile, service, folder=None, page=None):
        await self._check_profile(profile)
        mp2 = await self._mp2()
        item, offset = None, 0
        if page or folder:
            entry = self._entry(page, "page") if page else self._entry(folder, "item")
            if (entry["profile"], entry["service"]) != (profile, service):
                raise DemoError("That id belongs to another profile or service.")
            if folder and not page and text(entry["item"].get("StreamingMediaType")).lower() not in FOLDERS:
                raise DemoError("That item is not a folder; play it instead.")
            item, offset = entry["item"], entry.get("offset", 0)
        menu = await mp2.browse(profile, service, item, offset)
        return self._listing(menu, profile, service, offset)

    async def search(self, profile, service, query, category):
        if category not in SEARCH_CATEGORIES:
            raise DemoError("Search category must be one of {}.".format(SEARCH_CATEGORIES))
        if not isinstance(query, str) or not query.strip():
            raise DemoError("Search text is empty.")
        await self._check_profile(profile)
        mp2 = await self._mp2()
        menu = await mp2.navigate(
            profile,
            "SearchMenu",
            {
                "SearchProviderKey": service,
                "SearchText": query.strip(),
                "SearchCategory": category,
                "ItemCount": 20,
                "ItemOffset": 0,
            },
        )
        # The next page of a search is a browse of its ParentBrowseKey.
        return self._listing(menu, profile, service, 0)

    async def home(self, profile):
        await self._check_profile(profile)
        mp2 = await self._mp2()
        menu = await mp2.navigate(
            profile,
            "HomeScreenMenu",
            {"HomeScreenCategory": "All", "ItemCount": 20, "ItemOffset": 0},
        )
        return self._listing(menu, profile, None, 0, paged=False)

    async def favorites(self, profile):
        await self._check_profile(profile)
        mp2 = await self._mp2()
        entries = await mp2.favorites(profile)
        ordered = sorted(
            (value for value in entries.values() if isinstance(value, dict)),
            key=lambda value: value.get("OrderNumber", 0),
        )
        return {
            "profile": profile,
            "items": [
                self._summary(profile, None, value["MenuDataItems"])
                for value in ordered
                if isinstance(value.get("MenuDataItems"), dict)
            ],
        }

    async def _inputs(self):
        return (
            at_path(await self.rest.get("/Device/InputSources"), "/Device/InputSources/Inputs")
            or {}
        )

    async def _zone_outputs(self):
        zones = at_path(await self.rest.get("/Device/ZoneOutputs"), "/Device/ZoneOutputs") or {}
        self.zone_names = {
            key: text(zone.get("Name"))
            for key, zone in (zones.get("Zones") or {}).items()
            if isinstance(zone, dict)
        }
        return zones

    async def _check_zone(self, zone):
        """Fail at once on a zone id the device does not list (no routes or inputs read first)."""
        if self.zone_names is None or zone not in self.zone_names:
            await self._zone_outputs()  # also refreshes the list
        if zone not in self.zone_names:
            raise self._unknown("zone", zone, self.zone_names)

    async def _rest_tables(self):
        zones = await self._zone_outputs()
        routes = (
            at_path(await self.rest.get("/Device/AvMatrixRouting"), "/Device/AvMatrixRouting/Routes")
            or {}
        )
        return zones.get("Zones") or {}, routes, await self._inputs(), zones.get("Version", "0")

    def _player_inputs(self, inputs):
        """Only Player01 = first MediaPlayer input is confirmed; others need player_input."""
        media = [k for k, v in inputs.items() if v.get("AudioType") == "MediaPlayer"]
        mapping = {}
        if media:
            mapping["Player01"] = media[0]
        if self.config.player_input:
            if self.config.player_input not in media:
                raise DemoError("player_input is not a reported MediaPlayer input.")
            mapping[self.config.player] = self.config.player_input
        return mapping

    def _input_players(self, inputs):
        return {source: player for player, source in self._player_inputs(inputs).items()}

    @staticmethod
    def _zone_view(key, zone, routes, inputs, players_by_input):
        audio = zone.get("ZoneAudio") or {}
        source = (routes.get(key) or {}).get("AudioSource") or ""
        return {
            "zone": key,
            "name": text(zone.get("Name")),
            "volume": percent(audio.get("Volume")),
            "muted": audio.get("IsMuted"),
            "min_volume": percent(audio.get("MinVolume")),
            "max_volume": percent(audio.get("MaxVolume")),
            "grouped": zone.get("IsBussed") is not False,
            "source": source or None,
            "source_name": text((inputs.get(source) or {}).get("Name")) or None,
            "source_player": players_by_input.get(source),
            "reserved_input": (zone.get("ZoneBasedProviders") or {}).get("ReservedPlayer"),
        }

    async def zones(self):
        zones, routes, inputs, _ = await self._rest_tables()
        by_input = self._input_players(inputs)
        return {
            "zones": [
                self._zone_view(key, zone, routes, inputs, by_input)
                for key, zone in zones.items()
                if isinstance(zone, dict)
            ]
        }

    async def inputs(self):
        inputs = await self._inputs()
        by_input = self._input_players(inputs)
        return {
            "inputs": [
                {
                    "input": key,
                    "name": text(value.get("Name")),
                    "type": value.get("AudioType"),
                    "signal": value.get("IsSignalPresent"),
                    "player": by_input.get(key),
                }
                for key, value in inputs.items()
                if isinstance(value, dict)
            ]
        }

    async def _check_player(self, player):
        """Fail at once on a player id the device does not list. Asking the device
        for one (GetCresNextObject) is never answered and waits out the timeout."""
        await self._mp2()
        if player not in self.player_slots:
            players = await self.mp2.get("/Device/MediaPlayerNeXt/Players") or {}
            self.player_slots = set(players)  # a slot may have appeared since connecting
            if player not in self.player_slots:
                active = {
                    key: ""
                    for key, value in players.items()
                    if isinstance(value, dict) and value.get("PlayerState") != "ready"
                }
                raise self._unknown("player", player, active)

    async def _fresh_player(self, player):
        return (await (await self._mp2()).fresh_player(player)).data

    def _player_view(self, key, data):
        state = self.mp2.players[key].metadata() if key in self.mp2.players else {}
        nested = data.get("Player") or {}
        actions = data.get("AvailableActions")
        return {
            "player": key,
            "state": data.get("PlayerState"),
            "title": state.get("title", ""),
            "station": text(now_playing(data).get("StationName")),
            "artist": state.get("artist", ""),
            "album": state.get("album", ""),
            "duration": state.get("duration"),
            "position": state.get("position"),
            "service": nested.get("ProviderKey"),
            "profile": nested.get("ProfileKey"),
            "actions": actions if isinstance(actions, list) else [],
            "shuffle": nested.get("Shuffle"),
            "repeat": nested.get("Repeat"),
        }

    def _hearing(self, player, tables):
        """(input, zones that hear this player), or (None, None) when unconfirmed."""
        zones, routes, inputs, _ = tables
        source = self._player_inputs(inputs).get(player)
        if not source:
            return None, None
        heard = [
            self._zone_view(key, zones[key], routes, inputs, {source: player})
            for key, route in routes.items()
            if (route or {}).get("AudioSource") == source and key in zones
        ]
        return source, heard

    async def players(self):
        mp2 = await self._mp2()
        players = await mp2.get("/Device/MediaPlayerNeXt/Players") or {}
        try:
            tables, failure = await self._rest_tables(), None
        except DemoError as exc:  # show players even when REST is unavailable
            tables, failure = None, "unknown: {}".format(exc)
        views = []
        for key, data in players.items():
            if not isinstance(data, dict) or data.get("PlayerState") == "ready":
                continue
            view = self._player_view(key, mp2.players[key].data if key in mp2.players else data)
            view["input"], view["heard_in"] = (
                self._hearing(key, tables) if tables else (None, failure)
            )
            views.append(view)
        return {"players": views}

    # --- previews ----------------------------------------------------------

    async def _active_player(self, player):
        if not isinstance(player, str) or not player:
            raise DemoError("Name a player, for example Player01.")
        await self._check_player(player)
        data = await self._fresh_player(player)
        if data.get("PlayerState") == "ready":
            raise DemoError("{} is an unused player slot.".format(player))
        if player not in self.subscribed:  # became active after we connected
            await self.mp2.subscribe(player)
            self.subscribed.add(player)
        return data

    async def _zone(self, zone):
        await self._check_zone(zone)
        zones, routes, inputs, version = await self._rest_tables()
        if zone not in zones:  # removed since the check
            raise self._unknown("zone", zone, self.zone_names)
        check_zone_version(version)
        view = self._zone_view(zone, zones[zone], routes, inputs, self._input_players(inputs))
        if view["grouped"]:
            raise DemoError("{} is grouped; its level follows the group.".format(zone))
        return view, inputs

    async def preview(self, tool, args):
        """What the change would do, and a fingerprint of the state it was shown on."""
        if tool in ("play_item", "player_action"):
            preview, fingerprint = await self._player_preview(tool, args)
        else:
            preview, fingerprint = await self._zone_preview(tool, args)
        return preview, json.dumps(fingerprint, sort_keys=True, default=str)

    async def _player_preview(self, tool, args):
        player = args.get("player")
        data = await self._active_player(player)
        if tool == "player_action":
            self._options(args)  # validate before touching the device again
            data = await self._offered(args, data)
        view = self._player_view(player, data)
        source, heard = self._hearing(player, await self._rest_tables())
        preview = {"player": view, "heard_in": heard if source else "unknown"}
        if tool == "play_item":
            entry = self._entry(args.get("item"), "item")
            summary = self._summary(entry["profile"], entry["service"], entry["item"], register=False)
            if not summary["playable"]:
                raise DemoError("'{}' is a folder; browse it to pick a track.".format(summary["name"]))
            preview["change"] = "play '{}' on {}".format(summary["name"], player)
            preview["item"] = summary
        else:
            value = args.get("value")
            preview["change"] = "{} on {}{}".format(
                args["action"], player, "" if value is None else " ({})".format(value)
            )
        # A live station retitles itself with its programme: bind to the station.
        # A song: bind to title, artist and album (two recordings can share a title).
        what = identity(data)
        if not is_live(now_playing(data)):
            what["name"] = [what["name"], view["artist"], view["album"]]
        return preview, [view["state"], what, heard]

    async def _zone_preview(self, tool, args):
        zone, inputs = await self._zone(args.get("zone"))
        if tool == "set_volume":
            value = args.get("percent")
            if type(value) is not int or not 0 <= value <= 100:
                raise DemoError("percent must be a whole number from 0 to 100.")
            if zone["min_volume"] is None or zone["max_volume"] is None:
                raise DemoError("Zone did not report its volume limits; refusing to guess.")
            if not zone["min_volume"] <= value <= zone["max_volume"]:
                raise DemoError(
                    "{}% is outside {}'s limits ({}% to {}%).".format(
                        value, zone["name"], zone["min_volume"], zone["max_volume"]
                    )
                )
            change = "volume {:g}% -> {}%".format(zone["volume"], value)
        elif tool == "set_mute":
            if type(args.get("muted")) is not bool:
                raise DemoError("muted must be true or false.")
            change = "{} -> {}".format(
                "muted" if zone["muted"] else "unmuted",
                "muted" if args["muted"] else "unmuted",
            )
        elif tool == "set_route":
            source = args.get("input")
            if not isinstance(source, str) or (source and source not in inputs):
                raise DemoError("Unknown input '{}'; list_inputs shows them.".format(source))
            change = "source {} -> {}".format(
                zone["source_name"] or "none",
                text((inputs.get(source) or {}).get("Name")) or source or "none",
            )
        else:
            raise DemoError("Unknown change tool '{}'.".format(tool))
        preview = {"zone": zone, "change": "{}: {}".format(zone["name"] or zone["zone"], change)}
        return preview, [zone["volume"], zone["muted"], zone["source"]]

    @staticmethod
    def _options(args):
        """Validate an action and its value; return (ActionId, ActionIdOptions)."""
        name = args.get("action")
        if name not in ACTIONS:
            raise DemoError("action must be one of {}.".format(sorted(ACTIONS)))
        value = args.get("value")
        options = None
        if name == "seek":
            if type(value) is not int or value < 0:
                raise DemoError("seek needs value = position in whole seconds.")
            options = {"Position": value}
        elif name == "shuffle":
            if type(value) is not bool:
                raise DemoError("shuffle needs value = true or false.")
            options = {"ShufState": value}
        elif name == "repeat":
            if value not in REPEAT:
                raise DemoError("repeat needs value = off, track or list.")
            options = {"RepState": REPEAT[value]}
        elif value is not None:
            raise DemoError("{} takes no value.".format(name))
        return ACTIONS[name], options

    async def _offered(self, args, data=None):
        """Refuse an action the player does not offer. AvailableActions can lag a
        state behind, so give it a moment first. Returns the player data."""
        player, name = args["player"], args["action"]
        data = data or await self._fresh_player(player)
        duration = self.mp2.players[player].metadata()["duration"]
        if name == "seek" and duration > 0 and args["value"] > duration:
            raise DemoError("seek target is past the end of the track ({} s).".format(duration))
        deadline = time.monotonic() + 2

        def offered():
            actions = data.get("AvailableActions")
            return actions if isinstance(actions, list) else []

        while name not in UNLISTED and ACTIONS[name] not in offered():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DemoError(
                    "{} is not available now; the player offers: {}.".format(
                        name, ", ".join(offered()) or "nothing"
                    )
                )
            self.mp2.changed.clear()
            try:  # wake on the next push instead of polling
                await asyncio.wait_for(self.mp2.changed.wait(), remaining)
            except asyncio.TimeoutError:
                pass
            data = self.mp2.players[player].data
        return data

    # --- changes -----------------------------------------------------------

    async def change(self, tool, args):
        if tool in ("play_item", "player_action"):
            await self._check_player(args["player"])
        else:
            await self._check_zone(args["zone"])
        if tool == "play_item":
            return await self._play_item(args["player"], args["item"])
        if tool == "player_action":
            return await self._player_action(args)
        zone = args["zone"]
        if tool == "set_volume":
            await self.rest.set_audio(zone, "Volume", args["percent"] * 10)
        elif tool == "set_mute":
            await self.rest.set_audio(zone, "IsMuted", args["muted"])
        elif tool == "set_route":
            await self.rest.set_route(zone, args["input"])
        view, _ = await self._zone(zone)
        return {"verified": True, "zone": view}

    async def _play_item(self, player, item_id):
        entry = self._entry(item_id, "item")
        mp2 = await self._mp2()
        title = text(entry["item"].get("BrowseItemName"))
        previous = self.owned.get(player)
        # A timeout does not prove LoadSource had no effect, so the new item counts
        # as ours until the device says otherwise.
        self.owned[player] = {"name": title, "profile": entry["profile"], "service": entry["service"]}
        baseline = await mp2.load_source(
            player, entry["profile"], entry["service"], entry["item"]["SignedData"]
        )
        try:
            await mp2.wait_player(player, baseline, "playing", title, timeout=15)
        except BaseException:
            try:  # a refused load leaves the earlier item playing: it is still ours
                if previous and self._still_ours(await self._fresh_player(player), previous):
                    self.owned[player] = previous
            except Exception:
                pass
            raise
        return {"verified": True, "player": self._player_view(player, mp2.players[player].data)}

    def _confirmation(self, name, options, view, sent):
        """The push that proves the action happened."""
        if name == "play":
            return lambda d: d.get("PlayerState") == "playing"
        if name == "shuffle":
            return lambda d: (d.get("Player") or {}).get("Shuffle") == options["ShufState"]
        if name == "repeat":
            return lambda d: (d.get("Player") or {}).get("Repeat") == options["RepState"]
        if name == "seek":
            return lambda d: abs(now_playing(d).get("ElapsedSec", -999) - options["Position"]) <= 5
        if name in SKIPS:
            # A fresh item: new metadata, or the same title restarting at 0
            # (two recordings can share a title).
            return lambda d: bool(title_of(now_playing(d))) and (
                title_of(now_playing(d)) != view["title"] or now_playing(d).get("ElapsedSec") == 0
            )
        start, duration = view["position"] or 0, view["duration"] or 0

        def jumped(d):  # forward or rewind: a 15 s jump, not an ordinary tick
            at = now_playing(d).get("ElapsedSec")
            if not isinstance(at, (int, float)):
                return False
            expected = start + (time.monotonic() - sent if view["state"] == "playing" else 0)
            if name == "rewind":
                return at <= max(0, expected - 8)
            return at >= expected + 8 or (duration > 0 and at >= duration - 2)

        return jumped

    async def _player_action(self, args):
        player, name = args["player"], args["action"]
        mp2 = await self._mp2()
        action_id, options = self._options(args)
        view = self._player_view(player, await self._offered(args))
        if name == "play":
            self.owned[player] = identity(mp2.players[player].data)
        baseline = await mp2.action(player, action_id, options)
        test = self._confirmation(name, options, view, time.monotonic())
        try:
            await mp2.wait_delta(player, baseline, test, timeout=15 if name in SKIPS else 10)
        except BaseException:
            if name in SKIPS and player in self.owned:
                try:  # the skip may have applied: same profile and service is still ours
                    data = await self._fresh_player(player)
                    if data.get("PlayerState") == "playing" and same_source(
                        self.owned[player], identity(data)
                    ):
                        self.owned[player] = identity(data)
                except Exception:
                    pass
            raise
        data = mp2.players[player].data
        if (name == "play" or name in SKIPS) and player in self.owned:
            # Still ours after a skip: remember the new item for the shutdown pause.
            self.owned[player] = identity(data)
        return {"verified": True, "player": self._player_view(player, data)}

    async def pause(self, player):
        """Pause never needs approval: stopping sound is always allowed."""
        data = await self._active_player(player)
        if data.get("PlayerState") != "playing":
            return {"verified": True, "player": self._player_view(player, data)}
        baseline = await self.mp2.action(player, "Pause")
        await self.mp2.wait_player(player, baseline, "paused")
        return {"verified": True, "player": self._player_view(player, self.mp2.players[player].data)}
