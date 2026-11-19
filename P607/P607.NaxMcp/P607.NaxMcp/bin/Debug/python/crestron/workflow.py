"""The direct demo's fixed sequence; each step must be confirmed by the device."""

import asyncio
import time

from .errors import DemoError


def verified(status, state=None, volume=None):
    if status.get("verified") is not True or (state and status.get("state") != state):
        raise DemoError("Device did not verify the expected playback state.")
    if volume is not None and status.get("volume") != volume:
        raise DemoError("Device did not verify the expected zone volume.")


async def show_progress(controller, console, seconds):
    started = time.monotonic()
    for tick in range(seconds + 1):
        await asyncio.sleep(max(0, started + tick - time.monotonic()))
        status = await controller.snapshot()
        if status.get("state") != "playing":
            raise DemoError("Playback stopped during the timed demonstration.")
        console.metadata(status)
        console.progress(status, tick, seconds)
    console.finish_progress()


async def run_demo(controller, console, initial_seconds=30, resume_seconds=5):
    try:
        status = await controller.load_track()
        verified(status, state="playing")
        console.line("Playback confirmed")
        console.metadata(status)
        await show_progress(controller, console, initial_seconds)

        console.line("Pausing...")
        verified(await controller.pause(), state="paused")
        console.line("Verified: paused")

        console.line("Setting zone volume to 10%...")
        verified(await controller.set_volume(10), state="paused", volume=10)
        console.line("Verified: volume 10%")

        console.line("Resuming...")
        verified(await controller.play(), state="playing", volume=10)
        console.line("Verified: playing")
        await show_progress(controller, console, resume_seconds)

        console.line("Pausing...")
        status = await controller.pause()
        verified(status, state="paused", volume=10)
        console.line("Finished: player paused, zone volume 10%")
        return status
    except BaseException:
        console.finish_progress()
        try:
            status = await controller.pause()
            console.line("Cleanup: player {}".format(status.get("state", "unknown")))
        except Exception as exc:
            console.line("Cleanup could not verify pause: {}".format(exc))
        raise
