"""The simulated DM-NAX: one state object that both the MP2 WebSocket API and the
REST API read and change.

MP2 changes are announced through publish(path, delta); the WebSocket hub forwards
each one to the sessions subscribed to that path. REST has no pushes: clients read
back. Playback is simulated with a clock; no audio is produced.
"""

import copy
import random
import time
from collections import deque

from catalog import PLAYABLE, PROFILES, PROVIDER_NAMES, Catalog

SKIP_SECONDS = 15
RETITLE_SECONDS = 40  # a live station's "now on air" line changes this often
ZONE_NAMES = ["Kitchen", "Living Room", "Patio", "Primary Bedroom", "Office", "Dining",
              "Gym", "Den", "Guest Room", "Garage"]
PHYSICAL_INPUTS = [("Analog 1", "Analog"), ("Analog 2", "Analog"),
                   ("Digital S/PDIF", "Digital"), ("AES67 Stream", "Aes67")]
DEFAULT_FAULTS = {
    "refuse_load": False,     # LoadSource answers with a refusal Notification
    "silent_player": False,   # player actions are accepted but never applied or pushed
    "reply_delay": 0.0,       # seconds added before every MP2 reply/push and REST reply
    "reject_mp2_login": False,
    "reject_rest_login": False,
}


def nest(path, value):
    """{'Device': {...}} with value placed at /Device/a/b."""
    keys = path.strip("/").split("/")
    for key in reversed(keys):
        value = {key: value}
    return value


def at_path(document, path):
    current = document
    for key in path.strip("/").split("/"):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


class Player:
    def __init__(self, key, input_key):
        self.key = key
        self.input_key = input_key
        self.state = "stopped"
        self.profile = ""
        self.provider = ""
        self.signed = {}
        self.queue, self.index = [], 0
        self.shuffle, self.repeat = False, 0
        self.position, self.anchor = 0.0, time.monotonic()
        self.retitle_step, self.retitled_at = 0, time.monotonic()
        self.notification = None

    def elapsed(self, node):
        position = self.position
        if self.state == "playing":
            position += time.monotonic() - self.anchor
        if node and node.duration > 0:
            position = min(position, node.duration)
        return max(0.0, position)

    def set_position(self, seconds):
        self.position, self.anchor = float(seconds), time.monotonic()


class Device:
    def __init__(self, players=5, zones=5, faults=None, log_to_console=True):
        if not 1 <= players <= 8 or not 1 <= zones <= 10:
            raise ValueError("players must be 1-8 and zones 1-10")
        self.catalog = Catalog()
        self.listeners = []  # callables (path, delta) for MP2 pushes
        self.log_lines = deque(maxlen=200)
        self.log_to_console = log_to_console
        self.started = time.time()
        self.faults = dict(DEFAULT_FAULTS)
        self.faults.update(faults or {})
        self.notice_id = 0

        self.inputs = {}
        for index, (name, kind) in enumerate(PHYSICAL_INPUTS, 1):
            self.inputs["Input{:02d}".format(index)] = {"Name": name, "AudioType": kind}
        self.players = {}
        for index in range(1, players + 1):
            input_key = "Input{:02d}".format(len(PHYSICAL_INPUTS) + index)
            self.inputs[input_key] = {"Name": "Media Player {}".format(index),
                                      "AudioType": "MediaPlayer"}
            key = "Player{:02d}".format(index)
            self.players[key] = Player(key, input_key)
        player_inputs = [p.input_key for p in self.players.values()]
        self.zones, self.routes = {}, {}
        for index in range(1, zones + 1):
            key = "Zone{}".format(index)
            reserved = player_inputs[index - 1] if index <= len(player_inputs) else ""
            self.zones[key] = {"Name": ZONE_NAMES[index - 1], "Volume": 250, "IsMuted": False,
                               "MinVolume": 0, "MaxVolume": 1000, "ReservedPlayer": reserved}
            self.routes[key] = reserved

    # --- logging and pushes ---------------------------------------------------------

    def log(self, channel, message):
        line = {"t": time.time(), "channel": channel, "message": message}
        self.log_lines.append(line)
        if self.log_to_console:
            print("[{}] {:5} {}".format(time.strftime("%H:%M:%S"), channel, message), flush=True)

    def publish(self, path, delta):
        for listener in list(self.listeners):
            listener(path, delta)

    def _push_player(self, player, delta=None):
        if delta is None:
            delta = self.player_object(player)
        self.publish("/Device/MediaPlayerNeXt/Players/" + player.key, delta)

    # --- object views -------------------------------------------------------------

    def node(self, player):
        if not player.queue:
            return None
        return self.catalog.nodes[player.queue[player.index]]

    def actions(self, player):
        node = self.node(player)
        if node is None:
            return []
        if player.state == "stopped":
            return ["Play"]
        toggle = "Pause" if player.state == "playing" else "Play"
        if node.duration == 0:  # live station
            return [toggle, "Stop"]
        actions = [toggle, "Stop", "Shuffle", "Repeat", "Seek", "Ffwd", "Rewind"]
        many = len(player.queue) > 1
        if many and (player.shuffle or player.repeat == 2 or player.index < len(player.queue) - 1):
            actions.append("NextTrack")
        if many and (player.index > 0 or player.repeat == 2):
            actions.append("PreviousTrack")
        return actions

    def now_playing(self, player):
        node = self.node(player)
        blank = {"TrackTitle": "", "StationName": "", "ArtistName": "", "AlbumName": "",
                 "AlbumArtUrl": "", "StreamingMediaType": "", "Duration": -1, "ElapsedSec": 0}
        if node is None:
            return blank
        data = dict(blank, StreamingMediaType=node.kind, Duration=node.duration,
                    ElapsedSec=int(player.elapsed(node)))
        if node.kind == "station":
            data.update(StationName=node.name,
                        TrackTitle=self.catalog.programme(node.id, player.retitle_step))
        else:
            data.update(TrackTitle=node.name, ArtistName=node.artist, AlbumName=node.album)
        return data

    def player_object(self, player):
        return {
            "PlayerState": player.state,
            "AvailableActions": self.actions(player),
            "Player": {
                "ProfileKey": player.profile,
                "ProviderKey": player.provider,
                "Shuffle": player.shuffle,
                "Repeat": player.repeat,
                "SignedData": copy.deepcopy(player.signed),
                "NowPlayingData": self.now_playing(player),
            },
        }

    def input_signal(self, input_key):
        return any(p.input_key == input_key and p.state == "playing"
                   for p in self.players.values())

    def zone_object(self, key):
        zone = self.zones[key]
        return {
            "Name": zone["Name"],
            "IsBussed": False,
            "IsSignalDetected": bool(self.routes.get(key)) and not zone["IsMuted"]
            and self.input_signal(self.routes[key]),
            "ZoneAudio": {
                "Volume": zone["Volume"],
                "VolumedB": round(-80 + zone["Volume"] * 0.08, 1),
                "IsMuted": zone["IsMuted"],
                "MinVolume": zone["MinVolume"],
                "MaxVolume": zone["MaxVolume"],
            },
            "ZoneBasedProviders": {"ReservedPlayer": zone["ReservedPlayer"]},
        }

    def tree(self):
        """The whole CresNext object, as both APIs read it."""
        return {"Device": {
            "DeviceInfo": {
                "Model": "DM-NAX-4ZSA",
                "Name": "dmnax-server",
                "DeviceVersion": "1.0.0 (dmnax-server demo)",
                "SerialNumber": "DMNAX-DEMO-0001",
                "Version": "2.0.0",
            },
            "ZoneOutputs": {
                "Version": "2.1.0",
                "Zones": {key: self.zone_object(key) for key in self.zones},
            },
            "InputSources": {
                "Version": "2.0.0",
                "Inputs": {
                    key: dict(value, IsSignalPresent=self.input_signal(key))
                    for key, value in self.inputs.items()
                },
            },
            "AvMatrixRouting": {
                "Version": "2.0.0",
                "IsAudioAutoRoutingEnabled": False,
                "Routes": {key: {"AudioSource": source} for key, source in self.routes.items()},
            },
            "MediaPlayerNeXt": {
                "Players": {key: self.player_object(p) for key, p in self.players.items()},
            },
            "StreamingServices": {
                "UserProfiles": {
                    key: {
                        "Name": profile["Name"],
                        "AssignedProviders": {
                            provider: {"Name": PROVIDER_NAMES[provider], "IsAuthenticated": True}
                            for provider in profile["Providers"]
                        },
                    }
                    for key, profile in PROFILES.items()
                },
            },
            "MediaFavorites": {
                "Profiles": {
                    key: {"Favorites": self.catalog.favorites_list(key, with_signed=False)}
                    for key in PROFILES
                },
            },
        }}

    def read(self, path):
        if not isinstance(path, str) or not path.startswith("/Device"):
            return None
        return at_path(self.tree(), path)

    # --- REST writes -----------------------------------------------------------------

    def rest_write(self, change):
        """Apply a REST POST body; returns the Results list (one entry per leaf)."""
        results = []

        def result(path, status, info):
            results.append({"Path": "Device." + ".".join(path), "Property": path[-1],
                            "StatusId": status, "StatusInfo": info})

        def walk(path, value):
            if isinstance(value, dict):
                if not value:
                    result(path or ("Device",), -1,
                           "Empty object refused: it would delete configuration")
                for key, child in value.items():
                    walk(path + (key,), child)
                return
            self._write_leaf(path, value, result)

        device = change.get("Device") if isinstance(change, dict) else None
        if not isinstance(device, dict):
            result(("Device",), -1, "Body must be {\"Device\": {...}}")
        else:
            walk((), device)
        return results

    def _write_leaf(self, path, value, result):
        if len(path) == 5 and path[:2] == ("ZoneOutputs", "Zones") and path[3] == "ZoneAudio":
            zone = self.zones.get(path[2])
            if zone is None:
                return result(path, -1, "Unknown zone")
            if path[4] == "Volume":
                if type(value) is not int or not zone["MinVolume"] <= value <= zone["MaxVolume"]:
                    return result(path, -1, "Volume must be an integer within MinVolume..MaxVolume")
                old, zone["Volume"] = zone["Volume"], value
                self.log("REST", "{} volume {:g}% -> {:g}%".format(path[2], old / 10, value / 10))
                return result(path, 0, "OK")
            if path[4] == "IsMuted":
                if type(value) is not bool:
                    return result(path, -1, "IsMuted must be true or false")
                zone["IsMuted"] = value
                self.log("REST", "{} {}".format(path[2], "muted" if value else "unmuted"))
                return result(path, 0, "OK")
        if len(path) == 4 and path[:2] == ("AvMatrixRouting", "Routes") and path[3] == "AudioSource":
            if path[2] not in self.zones:
                return result(path, -1, "Unknown zone")
            if not isinstance(value, str) or (value and value not in self.inputs):
                return result(path, -1, "AudioSource must be an input key or \"\"")
            self.routes[path[2]] = value
            self.log("REST", "{} source -> {}".format(path[2], value or "none"))
            return result(path, 0, "OK")
        return result(path, -2, "Property is not writable on dmnax-server")

    # --- MP2 player actions --------------------------------------------------------------

    def _notify(self, player, message):
        self.notice_id += 1
        player.notification = {"NotiId": self.notice_id, "Msg": message,
                               "UserInputReq": "None", "UserInputs": {"Input1": "OK"}}
        self.log("MP2", "{} refused: {}".format(player.key, message))
        self._push_player(player, {"Notification": player.notification})

    def player_action(self, key, action, options):
        player = self.players.get(key)
        if player is None:
            return "Unknown PlayerId '{}'".format(key)
        options = options if isinstance(options, dict) else {}
        if action == "Notification":  # the client answers (dismisses) a prompt
            player.notification = None
            self._push_player(player, {"Notification": {}})
            return None
        if self.faults["silent_player"]:
            self.log("FAULT", "silent_player: ignored {} on {}".format(action, key))
            return None
        player.notification = None  # a new command replaces any earlier refusal
        handler = getattr(self, "_do_" + str(action), None)
        node = self.node(player)
        # Shuffle and Repeat apply to any loaded song, even a stopped one.
        mode_change = action in ("Shuffle", "Repeat") and node is not None and node.duration > 0
        if action != "LoadSource" and not mode_change and (
                handler is None or action not in self.actions(player)):
            if action == "Pause" and player.state != "playing" and node:
                return None  # already not playing: nothing to do
            self._notify(player, "Requested action not supported for this service")
            return None
        if handler is None:
            self._notify(player, "Requested action not supported for this service")
            return None
        handler(player, node, options)
        return None

    def _do_LoadSource(self, player, node, options):
        if self.faults["refuse_load"]:
            self._notify(player, "Set Station Failed: This track is not currently available.")
            return
        source = self.catalog.verify(options.get("SignedData"))
        if source is None or source.get("Node") == "search":
            self._notify(player, "Set Station Failed: invalid SignedData")
            return
        target = self.catalog.nodes.get(source["Node"])
        profile, provider = options.get("ProfileKey"), options.get("ProviderKey")
        if target is None or target.kind not in PLAYABLE:
            self._notify(player, "Set Station Failed: This item cannot be played directly; "
                                 "open it and play a track inside it.")
            return
        if provider != target.provider or provider not in self.catalog.providers(profile):
            self._notify(player, "Set Station Failed: profile or provider does not match the item")
            return
        player.queue, player.index = self.catalog.queue_for(source)
        player.profile, player.provider = profile, provider
        player.signed = options.get("SignedData")
        player.set_position(0)
        player.retitle_step, player.retitled_at = 0, time.monotonic()
        player.state = "playing" if options.get("AutoPlay", True) is not False else "stopped"
        self.log("MP2", "{} LoadSource '{}' ({}){}".format(
            player.key, target.name, PROVIDER_NAMES[provider],
            ", queue of {}".format(len(player.queue)) if len(player.queue) > 1 else ""))
        self._push_player(player)

    def _transport(self, player, node, state):
        player.set_position(player.elapsed(node))
        player.state = state
        self.log("MP2", "{} {}".format(player.key, state))
        self._push_player(player)

    def _do_Play(self, player, node, options):
        if player.state == "stopped":
            player.set_position(0)
        self._transport(player, node, "playing")

    def _do_Pause(self, player, node, options):
        self._transport(player, node, "paused")

    def _do_Stop(self, player, node, options):
        self._transport(player, node, "stopped")
        player.set_position(0)

    def _do_Seek(self, player, node, options):
        position = options.get("Position")
        if type(position) is not int or not 0 <= position <= node.duration:
            self._notify(player, "Seek position is outside the track")
            return
        player.set_position(position)
        self.log("MP2", "{} seek to {} s".format(player.key, position))
        self._push_player(player, {"Player": {"NowPlayingData": {"ElapsedSec": position}}})

    def _jump(self, player, node, seconds):
        player.set_position(min(max(0, player.elapsed(node) + seconds), node.duration))
        at = int(player.elapsed(node))
        self.log("MP2", "{} {} to {} s".format(player.key, "forward" if seconds > 0 else "rewind", at))
        self._push_player(player, {"Player": {"NowPlayingData": {"ElapsedSec": at}}})

    def _do_Ffwd(self, player, node, options):
        self._jump(player, node, SKIP_SECONDS)

    def _do_Rewind(self, player, node, options):
        self._jump(player, node, -SKIP_SECONDS)

    def _do_Shuffle(self, player, node, options):
        value = options.get("ShufState")
        if type(value) is not bool:
            self._notify(player, "ShufState must be true or false")
            return
        player.shuffle = value
        self.log("MP2", "{} shuffle {}".format(player.key, "on" if value else "off"))
        self._push_player(player, {"Player": {"Shuffle": value},
                                   "AvailableActions": self.actions(player)})

    def _do_Repeat(self, player, node, options):
        value = options.get("RepState")
        if value not in (0, 1, 2) or type(value) is not int:
            self._notify(player, "RepState must be 0 (off), 1 (track) or 2 (list)")
            return
        player.repeat = value
        self.log("MP2", "{} repeat {}".format(player.key, ("off", "track", "list")[value]))
        self._push_player(player, {"Player": {"Repeat": value},
                                   "AvailableActions": self.actions(player)})

    def _do_NextTrack(self, player, node, options):
        self._advance(player, 1, automatic=False)

    def _do_PreviousTrack(self, player, node, options):
        self._advance(player, -1, automatic=False)

    def _advance(self, player, step, automatic):
        count = len(player.queue)
        if automatic and player.repeat == 1:
            index = player.index
        elif player.shuffle and count > 1:
            index = random.choice([i for i in range(count) if i != player.index])
        else:
            index = player.index + step
            if not 0 <= index < count:
                if player.repeat == 2:
                    index %= count
                else:  # end of the queue
                    player.state = "stopped"
                    player.set_position(0)
                    self.log("MP2", "{} reached the end of its queue".format(player.key))
                    self._push_player(player)
                    return
        player.index = index
        player.set_position(0)
        player.state = "playing"
        self.log("MP2", "{} now playing '{}'".format(player.key, self.node(player).name))
        self._push_player(player)

    def tick(self):
        """Advance simulated time: end songs, retitle live stations."""
        for player in self.players.values():
            node = self.node(player)
            if player.state != "playing" or node is None:
                continue
            if node.duration > 0 and player.elapsed(node) >= node.duration:
                self._advance(player, 1, automatic=True)
            elif node.duration == 0 and time.monotonic() - player.retitled_at >= RETITLE_SECONDS:
                player.retitle_step += 1
                player.retitled_at = time.monotonic()
                self._push_player(player, {"Player": {"NowPlayingData": {
                    "TrackTitle": self.catalog.programme(node.id, player.retitle_step)}}})

    # --- status page ---------------------------------------------------------------------

    def status(self):
        players = []
        for player in self.players.values():
            node = self.node(player)
            data = self.now_playing(player)
            players.append({
                "player": player.key,
                "state": player.state,
                "title": data["TrackTitle"],
                "station": data["StationName"],
                "artist": data["ArtistName"],
                "album": data["AlbumName"],
                "duration": data["Duration"],
                "position": round(player.elapsed(node), 1) if node else 0,
                "service": PROVIDER_NAMES.get(player.provider, ""),
                "profile": player.profile,
                "shuffle": player.shuffle,
                "repeat": ("off", "track", "list")[player.repeat],
                "queue": "{}/{}".format(player.index + 1, len(player.queue)) if player.queue else "",
                "input": player.input_key,
                "notification": (player.notification or {}).get("Msg"),
            })
        zones = []
        for key in self.zones:
            zone = self.zone_object(key)
            source = self.routes.get(key, "")
            zones.append({
                "zone": key,
                "name": zone["Name"],
                "volume": zone["ZoneAudio"]["Volume"] / 10,
                "muted": zone["ZoneAudio"]["IsMuted"],
                "source": source,
                "source_name": self.inputs.get(source, {}).get("Name", ""),
                "signal": zone["IsSignalDetected"],
            })
        return {"model": "DM-NAX-4ZSA", "uptime": round(time.time() - self.started),
                "players": players, "zones": zones, "faults": self.faults,
                "log": list(self.log_lines)[-60:]}
