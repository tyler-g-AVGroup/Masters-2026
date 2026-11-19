"""Readable output, with in-place progress only when stdout is a terminal."""

import sys


def clock_text(seconds):
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return "--:--"
    seconds = int(seconds)
    return "{:02d}:{:02d}".format(seconds // 60, seconds % 60)


def safe_text(value):
    # Provider titles are data. Remove control characters before terminal output.
    return "".join(char if char.isprintable() else " " for char in str(value))


class Console:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self.inline = self.stream.isatty()
        self.last_metadata = None

    def line(self, message=""):
        print(safe_text(message), file=self.stream, flush=True)

    def show_plan(self, plan):
        self.line(
            "Device:  {} (firmware {})".format(
                plan["device"]["model"], plan["device"]["firmware"]
            )
        )
        self.line(
            "Profile: {} | {}".format(plan["profile"]["key"], plan["profile"]["name"])
        )
        self.line(
            "Service: {} | {}".format(plan["service"]["key"], plan["service"]["name"])
        )
        self.line("Player:  {} / {}".format(plan["player"], plan["input"]))
        self.line("Zone:    {} | {}".format(plan["zone"]["key"], plan["zone"]["name"]))
        self.line("Volume:  {:g}%".format(plan["initial_volume"]))
        self.line("Browsing: " + " > ".join(plan["track"]["browse_path"]))
        self.line("Selected: " + plan["track"]["title"])
        if not plan["routed"]:
            self.line(
                "Zone is not routed to this player; streaming will be silent on this output."
            )
        self.line(
            "Sequence: play {}s → pause → volume 10% → resume {}s → pause".format(
                plan["initial_seconds"], plan["resume_seconds"]
            )
        )

    def metadata(self, status):
        signature = tuple(
            status.get(key) for key in ("title", "artist", "album", "duration")
        )
        if signature == self.last_metadata:
            return
        self.last_metadata = signature
        self.finish_progress()
        for label, key in (
            ("Title", "title"),
            ("Artist", "artist"),
            ("Album", "album"),
        ):
            self.line(
                "{:<9} {}".format(label + ":", status.get(key) or "(not provided)")
            )
        duration = status.get("duration", 0)
        self.line(
            "Duration: {}".format(
                clock_text(duration)
                if duration > 0
                else ("live" if duration == 0 else "unknown")
            )
        )

    def progress(self, status, elapsed, total):
        position, duration = status.get("position", 0), status.get("duration", 0)
        filled = min(20, int(position / duration * 20)) if duration > 0 else 0
        marker = "~" if status.get("estimated") else ""
        message = "{} {}{} / {} [{}] demo {:02d}/{:02d}s | volume {:g}%".format(
            str(status.get("state", "unknown")).upper(),
            marker,
            clock_text(position),
            clock_text(duration) if duration > 0 else "--:--",
            "#" * filled + "-" * (20 - filled),
            int(elapsed),
            total,
            status.get("volume", 0),
        )
        print(
            ("\r" if self.inline else "") + safe_text(message),
            end="" if self.inline else "\n",
            file=self.stream,
            flush=True,
        )

    def finish_progress(self):
        if self.inline:
            print(file=self.stream, flush=True)
