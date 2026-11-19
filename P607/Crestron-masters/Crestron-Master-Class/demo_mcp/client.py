"""Menu-driven MCP client: you pick profile, service, item, player and zone;
the server does the device calls and asks for approval before each change."""

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

if __package__ is None:  # run as python demo_mcp/client.py: make the repo root importable
    sys.path[0] = str(Path(__file__).resolve().parents[1])
from typing import Any, Dict, List, Optional

from crestron.config import DEFAULT_CONFIG, ROOT
from crestron.device import ACTIONS, SEARCH_CATEGORIES
from demo_mcp.protocol import PROTOCOL_VERSION


# Above one tool call's own device waits (connect retry, 12 s replies, 15 s player
# checks), so the server reports a stuck device before the client gives up.
_TIMEOUT_SECONDS = 150


class McpClientError(Exception):
    pass


class StdioClient:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process
        self._next_id = 1

    async def request(
        self, method: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        if self.process.stdin is None or self.process.stdout is None:
            raise McpClientError("MCP subprocess streams are unavailable")
        request_id = self._next_id
        self._next_id += 1
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write(
            (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        )
        await self.process.stdin.drain()
        while True:
            try:
                line = await asyncio.wait_for(
                    self.process.stdout.readline(), _TIMEOUT_SECONDS
                )
            except asyncio.TimeoutError:
                raise McpClientError(
                    "Timed out waiting for MCP response to {}".format(method)
                )
            if not line:
                raise McpClientError(
                    "MCP server exited before responding to {}".format(method)
                )
            try:
                response = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise McpClientError("MCP server wrote invalid JSON to stdout")
            # A server notification (for example tools/list_changed) is not the reply.
            if not (isinstance(response, dict) and "id" not in response and "method" in response):
                break
        if not isinstance(response, dict) or response.get("id") != request_id:
            raise McpClientError(
                "MCP response id did not match the outstanding request"
            )
        if "error" in response:
            error = response["error"]
            raise McpClientError(
                "MCP {} error: {}".format(error.get("code"), error.get("message"))
            )
        if "result" not in response:
            raise McpClientError("MCP response did not include result or error")
        return response["result"]

    async def notify(
        self, method: str, params: Optional[Dict[str, Any]] = None
    ) -> None:
        if self.process.stdin is None:
            raise McpClientError("MCP subprocess stdin is unavailable")
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write(
            (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        )
        await self.process.stdin.drain()

    async def close(self, timeout: float = 10) -> Optional[int]:
        """Close stdin so the server shuts down (pausing what it started); return its
        exit status, which is nonzero if it had to be stopped or its cleanup failed."""
        process = self.process
        if process.stdin is not None:
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout)
        except asyncio.TimeoutError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 3)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            return process.returncode or 1
        return process.returncode

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        result = await self.request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        if not isinstance(result, dict):
            raise McpClientError("Tool {} returned an invalid result".format(name))
        if result.get("isError"):
            value = result.get("structuredContent", {})
            raise McpClientError("Tool {} failed: {}".format(name, value))
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            raise McpClientError("Tool {} returned no structured result".format(name))
        return structured



def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return "q"


def choose(title: str, rows: List[str], keys: str = "") -> Optional[Any]:
    """Number the rows; return the picked index, a letter from keys, or None for quit."""
    print(title)
    for number, row in enumerate(rows, 1):
        print("  {:>2}) {}".format(number, row))
    while True:
        answer = ask("Pick 1-{}{} (q quits): ".format(len(rows), keys and ", " + keys)).lower()
        if answer == "q":
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(rows):
            return int(answer) - 1
        if answer and answer + ")" in keys.split():  # the letter keys, e.g. "v)"
            return answer


def rooms(heard: Any) -> str:
    """The zones that hear a player, as list_players and previews report them."""
    if not isinstance(heard, list):
        return "zones unknown (this player's input is not confirmed)"
    return ", ".join(
        "{} {:g}%{}".format(z["name"], z["volume"], " muted" if z["muted"] else "")
        for z in heard
    ) or "no zone is routed to this player"


def describe_player(player: Dict[str, Any]) -> str:
    return "{} {}: {} | heard in: {}".format(
        player["player"], player.get("state"), player.get("title") or "nothing",
        rooms(player.get("heard_in")),
    )  # fmt: skip


class Menu:
    def __init__(self, client: StdioClient) -> None:
        self.client = client

    async def call(self, tool: str, **args: Any) -> Dict[str, Any]:
        return await self.client.call_tool(tool, args)

    async def approve(self, tool: str, **args: Any) -> Optional[Dict[str, Any]]:
        """Preview, ask the human, then confirm with the one-time token."""
        first = await self.call(tool, **args)
        preview = first["preview"]
        print("Preview: " + preview["change"])
        if "heard_in" in preview:
            print("  Heard in: " + rooms(preview["heard_in"]))
        if ask("Do it? [y/N]: ").lower() != "y":
            print("Cancelled; nothing changed.")
            return None
        result = await self.call(tool, confirm=True, token=first["token"], **args)
        print("Done and verified by the device.")
        return result

    async def pick(self, tool: str, key: str, label, **args: Any) -> Optional[Dict[str, Any]]:
        rows = (await self.call(tool, **args))[key]
        if not rows:
            print("Nothing to pick.")
            return None
        index = choose("{}:".format(key.capitalize()), [label(row) for row in rows])
        return rows[index] if isinstance(index, int) else None

    async def run(self) -> None:
        profile = await self.pick(
            "list_profiles", "profiles", lambda p: "{} | {}".format(p["profile"], p["name"])
        )
        if not profile:
            return
        service = await self.pick(
            "list_services",
            "services",
            lambda s: "{} | {}{}".format(
                s["service"], s["name"], "" if s["signed_in"] else " (not signed in)"
            ),
            profile=profile["profile"],
        )
        if service:
            await self.browse(profile["profile"], service)

    async def browse(self, profile: str, service: Dict[str, Any]) -> None:
        stack = [{"folder": None, "page": None, "path": [service["name"]]}]
        while True:
            frame = stack[-1]
            args = {"profile": profile, "service": service["service"]}
            for key in ("folder", "page"):
                if frame[key]:
                    args[key] = frame[key]
            try:
                listing = await self.call("browse", **args)
            except McpClientError as exc:
                print(exc)
                if len(stack) == 1:
                    return
                stack.pop()
                continue
            keys = "n) next  s) search  f) favorites  h) home  c) controls  b) back"
            choice = self.listing(" > ".join(frame["path"]), listing, keys)
            if choice is None:
                return
            if choice == "b":
                if len(stack) > 1:
                    stack.pop()
            elif choice == "n":
                if listing.get("next_page"):
                    stack.append(dict(frame, page=listing["next_page"]))
                else:
                    print("No more pages.")
            elif choice == "c":
                if not await self.controls():
                    return
            elif choice in ("s", "f", "h"):
                if not await self.other_listing(choice, profile, service):
                    return
            elif choice["folder"]:
                stack.append({"folder": choice["id"], "page": None, "path": frame["path"] + [choice["name"]]})
            elif choice["playable"]:
                await self.play(choice)
                if not await self.controls():
                    return

    @staticmethod
    def listing(title: str, listing: Dict[str, Any], keys: str) -> Any:
        items = [item for item in listing["items"] if item.get("id")]
        rows = [
            "[{}] {}{}".format(
                item["kind"], item["name"], " | " + item["artist"] if item["artist"] else ""
            )
            for item in items
        ]
        if not rows:
            print(title + ": (empty)")
        answer = choose(title + ":", rows, keys)
        return items[answer] if isinstance(answer, int) else answer

    async def other_listing(self, key: str, profile: str, service: Dict[str, Any]) -> bool:
        try:
            if key == "s":
                text = ask("Search text: ")
                category = ask("Category ({}) [song]: ".format(", ".join(SEARCH_CATEGORIES))) or "song"
                listing = await self.call(
                    "search", profile=profile, service=service["service"], text=text, category=category
                )
                title = "Search '{}'".format(text)
            elif key == "f":
                listing, title = await self.call("list_favorites", profile=profile), "Favorites"
            else:
                listing, title = await self.call("home_screen", profile=profile), "Home"
        except McpClientError as exc:
            print(exc)
            return True
        choice = self.listing(title, listing, "b) back")
        if choice is None:
            return False
        if isinstance(choice, dict) and choice["playable"]:
            await self.play(choice)
            return await self.controls()
        if isinstance(choice, dict):
            print("Open folders from the service menu; this list shows playable items best.")
        return True

    async def choose_player(self) -> Optional[str]:
        player = await self.pick("list_players", "players", describe_player)
        return player["player"] if player else None

    async def play(self, item: Dict[str, Any]) -> None:
        player = await self.choose_player()
        if not player:
            return
        try:
            await self.approve("play_item", player=player, item=item["id"])
        except McpClientError as exc:
            print(exc)

    async def controls(self) -> bool:
        """Player and zone controls. Returns False to quit, True to go back to browsing."""
        actions = ["status", "pause"] + list(ACTIONS)
        while True:
            answer = choose(
                "Controls:",
                actions,
                "v) volume  m) mute  r) route  b) browse",
            )
            if answer is None:
                return False
            if answer == "b":
                return True
            try:
                if isinstance(answer, int):
                    await self.player_control(actions[answer])
                else:
                    await self.zone_control(answer)
            except McpClientError as exc:
                print(exc)

    async def player_control(self, action: str) -> None:
        if action == "status":
            for player in (await self.call("list_players"))["players"]:
                print(describe_player(player))
            return
        player = await self.choose_player()
        if not player:
            return
        if action == "pause":
            result = await self.call("pause", player=player)
            print("Verified: " + describe_player(result["player"]).split(" | ")[0])
            return
        args = {"player": player, "action": action}
        if action == "seek":
            answer = ask("Position in seconds: ")
            if not answer.isdigit():
                print("Enter whole seconds.")
                return
            args["value"] = int(answer)
        elif action == "shuffle":
            args["value"] = ask("Shuffle on? [y/N]: ").lower() == "y"
        elif action == "repeat":
            args["value"] = ask("Repeat (off, track, list) [off]: ") or "off"
        await self.approve("player_action", **args)

    async def zone_control(self, key: str) -> None:
        zone = await self.pick(
            "list_zones",
            "zones",
            lambda z: "{} | {} {:g}%{} | source: {}".format(
                z["zone"], z["name"], z["volume"], " muted" if z["muted"] else "", z["source_name"] or "none"
            ),
        )
        if not zone:
            return
        if key == "v":
            answer = ask("Volume % ({:g} to {:g}): ".format(zone["min_volume"], zone["max_volume"]))
            if answer.isdigit():
                await self.approve("set_volume", zone=zone["zone"], percent=int(answer))
        elif key == "m":
            await self.approve("set_mute", zone=zone["zone"], muted=not zone["muted"])
        else:
            source = await self.pick(
                "list_inputs",
                "inputs",
                lambda i: "{} | {}{}".format(i["input"], i["name"], " ({})".format(i["player"]) if i["player"] else ""),
            )
            if source:
                await self.approve("set_route", zone=zone["zone"], input=source["input"])


def script(module: str) -> str:
    """The file of an entry module, so it starts the same from any directory."""
    return str(ROOT / (module.replace(".", "/") + ".py"))


async def _start(config_path: str, module: str) -> StdioClient:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        script(module),
        "--config",
        config_path,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=None,
        # Keep terminal Ctrl-C away from the server: the client closes stdin, and
        # the server pauses what it started and shuts down by itself.
        **(
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt"
            else {"start_new_session": True}
        ),
    )
    client = StdioClient(process)
    try:
        result = await client.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "crestron-demo-client", "version": "0.1.0"},
            },
        )
        if (
            not isinstance(result, dict)
            or result.get("protocolVersion") != PROTOCOL_VERSION
        ):
            raise McpClientError(
                "Server did not negotiate MCP {}".format(PROTOCOL_VERSION)
            )
        await client.notify("notifications/initialized")
        return client
    except Exception:
        await client.close(timeout=3)
        raise


async def _run(args: argparse.Namespace, module: str = "demo_mcp.server") -> int:
    client: Optional[StdioClient] = None
    exit_code = 0
    # asyncio.run (3.11+) turns Ctrl-C into a task cancel, which a blocking input()
    # prompt never sees. Restore the plain KeyboardInterrupt so a prompt stops too.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        client = await _start(os.path.abspath(args.config), module)
        await Menu(client).run()
    except (McpClientError, OSError, ValueError) as exc:
        print("MCP client error: {}".format(exc), file=sys.stderr)
        exit_code = 1
    finally:
        # Quit or Ctrl-C: the server pauses what it started (and still plays) as it
        # shuts down, and prints what it paused.
        if client is not None:
            status = await client.close()
            if status != 0:
                print("MCP server exited with status {}.".format(status), file=sys.stderr)
                exit_code = 1
            if exit_code == 0:
                print("Connections closed")
    return exit_code


def main(server_module: str = "demo_mcp.server") -> int:
    parser = argparse.ArgumentParser(description="Crestron MCP menu client")
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help="Path to the local Crestron demo config JSON (default: config/config.json)",
    )
    try:
        return asyncio.run(_run(parser.parse_args(), server_module))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
