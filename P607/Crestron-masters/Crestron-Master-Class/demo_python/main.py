"""Direct demo: python demo_python/main.py"""

import argparse
import asyncio
import signal
import sys
from pathlib import Path

if __package__ is None:  # run as python demo_python/main.py: make the repo root importable
    sys.path[0] = str(Path(__file__).resolve().parents[1])

from crestron.config import DEFAULT_CONFIG, load_config
from crestron.console import Console
from crestron.controller import Controller
from crestron.errors import DemoError
from crestron.workflow import run_demo


async def run(args):
    controller = Controller(load_config(args.config))
    console = Console()
    primary_error = None
    try:
        console.line("Connecting to MP2.0 and REST...")
        plan = await controller.prepare()
        console.show_plan(plan)
        if args.check:
            console.line(
                "Read-only check complete; playback and volume were unchanged."
            )
            return
        if (
            not args.execute
            and input("Run this exact sequence? Type 'yes': ").strip().lower() != "yes"
        ):
            console.line("Demo cancelled.")
            return
        try:
            # Before 3.11, Ctrl-C raised wherever the loop was and could break the
            # device connection before the cleanup pause; cancel this task instead.
            asyncio.get_running_loop().add_signal_handler(
                signal.SIGINT, asyncio.current_task().cancel
            )
        except NotImplementedError:
            pass  # Windows keeps the default Ctrl-C handling
        await run_demo(
            controller, console, plan["initial_seconds"], plan["resume_seconds"]
        )
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            await controller.close()
        except Exception as exc:
            if primary_error is None:
                raise
            print("Connection cleanup failed: {}".format(exc), file=sys.stderr)
        else:
            console.line("Connections closed")


def main():
    parser = argparse.ArgumentParser(
        description="Play the first track on the first signed-in service, then demonstrate zone volume."
    )
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG, help="Local device configuration"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Discover and display the plan without changing playback or volume",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Authorize the displayed sequence without an interactive prompt",
    )
    try:
        asyncio.run(run(parser.parse_args()))
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("Interrupted.", file=sys.stderr)
        return 130
    except DemoError as exc:
        print("Demo error: {}".format(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
