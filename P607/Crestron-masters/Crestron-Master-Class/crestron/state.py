"""Merge partial player updates and estimate time between position pushes."""

import copy
import json
import time


def parse_messages(frame):
    if isinstance(frame, bytes):
        frame = frame.decode("utf-8")
    decoder = json.JSONDecoder()
    offset = 0
    while offset < len(frame):
        while offset < len(frame) and frame[offset].isspace():
            offset += 1
        if offset == len(frame):
            break
        value, offset = decoder.raw_decode(frame, offset)
        if not isinstance(value, dict):
            raise ValueError("MP2 message must be a JSON object")
        yield value


def at_path(document, path):
    current = document
    for key in path.strip("/").split("/"):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def merge(target, update):
    for key, value in update.items():
        if key == "AvailableActions" and value == {}:
            continue  # The amplifier briefly sends {} during transport changes.
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def text(value):
    return value.strip() if isinstance(value, str) else ""


def is_live(now_playing):
    return now_playing.get("Duration") == 0


def title_of(now_playing):
    """The display title: TrackTitle, else StationName (TIDAL puts song titles there)."""
    return text(now_playing.get("TrackTitle")) or text(now_playing.get("StationName"))


def identity(player):
    """What a player object is playing, for ownership checks: the station for live
    radio (its programme title changes), else the title; plus profile and service."""
    nested = player.get("Player") or {}
    now = nested.get("NowPlayingData") or {}
    return {
        "name": text(now.get("StationName")) if is_live(now) else title_of(now),
        "profile": nested.get("ProfileKey"),
        "service": nested.get("ProviderKey"),
    }


def same_source(mine, other):
    """Same profile and service, where both are known."""
    return all(
        not mine.get(key) or not other.get(key) or mine[key] == other[key]
        for key in ("profile", "service")
    )


def same_item(now_playing, name):
    """True when the playing item is the expected song or station.

    Songs: the title (TrackTitle, else TIDAL's StationName). Live radio retitles
    TrackTitle with each programme, so its stable StationName also counts.
    """
    wanted = name.casefold()
    title = title_of(now_playing)
    station = text(now_playing.get("StationName"))
    return title.casefold() == wanted or (
        is_live(now_playing) and station.casefold() == wanted
    )


class PlayerState:
    def __init__(self, clock=time.monotonic):
        self.data = {}
        self.clock = clock
        self.position = 0.0
        self.anchor = clock()
        self.has_position = False

    def elapsed(self):
        position = self.position
        if self.data.get("PlayerState") == "playing":
            position += self.clock() - self.anchor
        duration = (
            self.data.get("Player", {}).get("NowPlayingData", {}).get("Duration", 0)
        )
        if isinstance(duration, (int, float)) and duration > 0:
            position = min(position, duration)
        return max(0.0, position)

    def update(self, delta, pushed=True):
        if not isinstance(delta, dict):
            return
        before = self.elapsed()
        old_state = self.data.get("PlayerState")
        now_playing = delta.get("Player", {}).get("NowPlayingData", {})
        new_title = title_of(now_playing)
        old_title = self.metadata()["title"]
        old_playing = self.data.get("Player", {}).get("NowPlayingData", {})
        # A live station retitling itself is not a new item: keep the timer running.
        same_station = is_live(old_playing) and text(
            now_playing.get("StationName", old_playing.get("StationName"))
        ) == text(old_playing.get("StationName"))
        title_changed = bool(new_title and new_title != old_title) and not same_station
        if title_changed:
            self.position, self.anchor = 0.0, self.clock()
        merge(self.data, delta)
        # Polled ElapsedSec is often zero even while audio is playing. Only
        # initial snapshots and actual pushes may re-anchor the running timer.
        elapsed = now_playing.get("ElapsedSec")
        if isinstance(elapsed, (int, float)) and (pushed or not self.has_position):
            self.position, self.anchor = float(elapsed), self.clock()
            self.has_position = True
        elif (
            not title_changed
            and "PlayerState" in delta
            and old_state != self.data.get("PlayerState")
        ):
            self.position, self.anchor = before, self.clock()

    def metadata(self):
        data = self.data.get("Player", {}).get("NowPlayingData", {})
        return {
            "state": self.data.get("PlayerState", "unknown"),
            "title": title_of(data),
            "artist": text(data.get("ArtistName")),
            "album": text(data.get("AlbumName")),
            "duration": data.get("Duration", -1),  # missing = unknown, 0 = live
            "position": round(self.elapsed(), 1),
            "estimated": True,
        }
