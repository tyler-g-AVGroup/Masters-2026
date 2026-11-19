"""Run every real entry point, then restore the explicitly selected test zone.

MCP servers are driven through their tools (preview, then confirm), like the menu
client does; the direct demo runs its scripted sequence.
"""

import argparse
import asyncio
import datetime
import json
import sys
from pathlib import Path

if __package__ is None:
    sys.path[:0] = [str(Path(__file__).resolve().parents[1])]

from crestron.config import DEFAULT_CONFIG, load_config
from crestron.controller import Controller
from crestron.errors import DemoError
from crestron.state import at_path
import demo_mcp_sdk
from demo_mcp.client import McpClientError, _start, script


async def approve(client, tool, **args):
    """Preview, then confirm with the one-time token, as a person approving would."""
    first = await client.call_tool(tool, args)
    return await client.call_tool(tool, dict(args, confirm=True, token=first["token"]))


def first(items, test, what):
    for item in items:
        if test(item):
            return item
    raise DemoError("No {} found.".format(what))


async def tour(module, config_path, zone=None, hold=30, resume=5):
    """Through MCP tools: pick profile, service and the first playable item, play,
    pause, set the zone to 10%, resume, pause. Returns what the tools reported."""
    config = load_config(config_path)
    client = await _start(str(Path(config_path).resolve()), module)
    try:
        call = client.call_tool
        profile = (await call("list_profiles", {}))["profiles"][0]["profile"]
        wanted = (config.service or "").casefold()
        service = first(
            (await call("list_services", {"profile": profile}))["services"],
            lambda s: wanted in (s["service"].casefold(), s["name"].casefold())
            if wanted
            else s["signed_in"],
            "service",
        )["service"]
        where = {"profile": profile, "service": service}
        listing = await call("browse", where)
        if config.folder:
            folder = first(
                listing["items"],
                lambda i: i["name"].casefold() == config.folder.casefold(),
                "folder " + config.folder,
            )
            listing = await call("browse", dict(where, folder=folder["id"]))
        budget = 40  # browse requests, like the direct demo's limits

        async def find(listing, depth):
            """Depth first, in menu order; skip folders that are empty or refuse."""
            nonlocal budget
            items = list(listing["items"])
            while listing.get("next_page") and budget > 0:  # later pages too
                budget -= 1
                listing = await call("browse", dict(where, page=listing["next_page"]))
                items += listing["items"]
            for entry in items:
                if entry["playable"]:
                    return entry
            for entry in items:
                if not entry["folder"] or depth >= 6 or budget <= 0:
                    continue
                budget -= 1
                try:
                    inner = await call("browse", dict(where, folder=entry["id"]))
                except McpClientError:  # e.g. an empty History folder refuses
                    continue
                found = await find(inner, depth + 1)
                if found:
                    return found
            return None

        item = await find(listing, 0)
        if item is None:
            raise DemoError("No playable item within 6 folder levels and 40 requests.")
        player = config.player
        await approve(client, "play_item", player=player, item=item["id"])
        await asyncio.sleep(hold)
        await call("pause", {"player": player})
        if zone is None:  # the zone that reserves this player's input
            players = (await call("list_players", {}))["players"]
            source = first(players, lambda p: p["player"] == player, player)["input"]
            zone = first(
                (await call("list_zones", {}))["zones"],
                lambda z: z["reserved_input"] == source,
                "zone for " + player,
            )["zone"]
        await approve(client, "set_volume", zone=zone, percent=10)
        await approve(client, "player_action", player=player, action="play")
        await asyncio.sleep(resume)
        final = await call("pause", {"player": player})
        zones = (await call("list_zones", {}))["zones"]
        toured = {
            "item": item["name"],
            "player_state": final["player"]["state"],
            "zone": zone,
            "volume": first(zones, lambda z: z["zone"] == zone, zone)["volume"],
        }
    finally:
        status = await client.close(timeout=15)
    if status != 0:  # its shutdown pause or cleanup failed
        raise DemoError("MCP server exited with status {}.".format(status))
    return toured


async def _pause_for_cleanup(observer):
    """Confirm current playback through MP2 before restoring the saved mute."""
    player_path = "/Device/MediaPlayerNeXt/Players/" + observer.config.player
    player = await observer.mp2.get(player_path)
    state = player.get("PlayerState") if isinstance(player, dict) else None
    if state not in ("paused", "stopped", "playing"):
        raise DemoError("Fresh player read did not report a usable playback state.")
    if state == "playing":
        baseline = await observer.mp2.action(observer.config.player, "Pause")
        await observer.mp2.wait_player(observer.config.player, baseline, "paused")
        player = await observer.mp2.get(player_path)
    if not isinstance(player, dict) or player.get("PlayerState") not in (
        "paused",
        "stopped",
    ):
        raise DemoError(
            "Fresh player read did not confirm playback was paused or stopped."
        )


async def verify(args):
    observer = Controller(load_config(args.config))
    report = {
        "date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "runs": [],
        "cleanup_errors": [],
    }
    saved = None
    changed = False
    try:
        plan = await observer.prepare()
        zone_key, input_key = plan["zone"]["key"], plan["input"]
        zone_path = "/Device/ZoneOutputs/Zones/" + zone_key
        zone = at_path(await observer.rest.get(zone_path), zone_path)
        routes = (
            at_path(
                await observer.rest.get("/Device/AvMatrixRouting"),
                "/Device/AvMatrixRouting/Routes",
            )
            or {}
        )
        saved = {
            "zone": zone_key,
            "route": routes.get(zone_key, {}).get("AudioSource", ""),
            "volume": zone["ZoneAudio"]["Volume"],
            "muted": zone["ZoneAudio"]["IsMuted"],
        }
        report.update(
            {
                "device": plan["device"],
                "python": sys.version.split()[0],
                "player": plan["player"],
                "zone": plan["zone"],
                "service": plan["service"],
                "saved": saved,
            }
        )
        if not plan["routed"] and not args.route:
            raise DemoError(
                "Zone is not routed. Pass --route only after authorizing temporary test routing."
            )
        quiet = min(saved["volume"], 200)
        if quiet < zone["ZoneAudio"]["MinVolume"]:
            raise DemoError("Cannot set a quiet test level within this zone's limits.")
        changed = True
        await observer.rest.set_audio(zone_key, "IsMuted", True)
        await observer.rest.set_audio(zone_key, "Volume", quiet)
        if args.route:
            await observer.rest.set_route(zone_key, input_key)
        await observer.rest.set_audio(zone_key, "IsMuted", saved["muted"])
        print(
            "Live test setup verified: {} routed to {}, initial volume {:g}%.".format(
                zone_key, input_key, quiet / 10
            ),
            flush=True,
        )

        entry_points = [("mcp", "demo_mcp.server")]
        if demo_mcp_sdk.available():
            entry_points.append(("mcp_sdk", "demo_mcp_sdk.server"))
        entry_points.append(("direct", "demo_python.main"))
        for name, module in entry_points:
            # Every run starts from the same quiet level. Changes are verified
            # through a separate observer connection rather than trusting stdout.
            await observer.rest.set_audio(zone_key, "Volume", quiet)
            print(
                "Running {} entry point (30 seconds + 5 seconds)...".format(name),
                flush=True,
            )
            if name != "direct":
                toured = await tour(module, args.config, zone_key)  # failures propagate
                code, errors = 0, ""
                output = "MCP tools reported: {}".format(json.dumps(toured))
            else:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-u",
                    script(module),
                    "--config",
                    str(Path(args.config).resolve()),
                    "--execute",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), 200)
                except BaseException:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), 15)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
                    raise
                code, output, errors = process.returncode, stdout.decode(), stderr.decode()
            Path("verification_{}.log".format(name)).write_text(output + errors)
            print(output, flush=True)
            if errors:
                print(errors, file=sys.stderr, flush=True)
            player_path = "/Device/MediaPlayerNeXt/Players/" + plan["player"]
            player = await observer.mp2.get(player_path)
            zone = at_path(await observer.rest.get(zone_path), zone_path)
            metadata = observer.mp2.players[plan["player"]].metadata()
            result = {
                "entry_point": module,
                "exit_code": code,
                "player_state": player.get("PlayerState"),
                "volume": zone["ZoneAudio"]["Volume"],
                "title": metadata["title"],
                "artist": metadata["artist"],
                "album": metadata["album"],
                "duration": metadata["duration"],
                "progress_30s": "demo 30/30s" in output,
                "progress_5s": "demo 05/05s" in output,
                "volume_readback_message": "Verified: volume 10%" in output,
            }
            result["verified"] = (
                code == 0
                and result["player_state"] == "paused"
                and result["volume"] == 100
                # The scripted direct demo also prints its progress and read-back.
                and (
                    name != "direct"
                    or (
                        result["progress_30s"]
                        and result["progress_5s"]
                        and result["volume_readback_message"]
                    )
                )
            )
            report["runs"].append(result)
            if not result["verified"]:
                raise DemoError(
                    "{} live verification failed; see verification_{}.log.".format(
                        name, name
                    )
                )
            print(
                "Independent read-back verified {}: paused, volume 10%.".format(name),
                flush=True,
            )
            await asyncio.sleep(10)  # Do not reconnect to the device in a tight loop.
    finally:
        if saved and changed:
            paused = False
            muted = False
            try:
                await observer.rest.set_audio(saved["zone"], "IsMuted", True)
                muted = True
            except Exception as exc:
                report["cleanup_errors"].append("mute: {}".format(exc))
            try:
                await _pause_for_cleanup(observer)
                paused = True
            except Exception as exc:
                report["cleanup_errors"].append("pause: {}".format(exc))
            if muted or paused:
                for name, operation in (
                    (
                        "route",
                        lambda: observer.rest.set_route(saved["zone"], saved["route"]),
                    ),
                    (
                        "volume",
                        lambda: observer.rest.set_audio(
                            saved["zone"], "Volume", saved["volume"]
                        ),
                    ),
                ):
                    try:
                        await operation()
                    except Exception as exc:
                        report["cleanup_errors"].append("{}: {}".format(name, exc))
            if paused:
                try:
                    await observer.rest.set_audio(
                        saved["zone"], "IsMuted", saved["muted"]
                    )
                except Exception as exc:
                    report["cleanup_errors"].append("restore mute: {}".format(exc))
            elif muted:
                report["cleanup_errors"].append(
                    "Player pause could not be verified; zone was left muted."
                )
            else:
                report["cleanup_errors"].append(
                    "Player pause and zone mute could not be verified; routing and volume were not restored."
                )
            report["settings_restored"] = paused and not report["cleanup_errors"]
            print(
                "Live test settings restored: {}".format(report["settings_restored"]),
                flush=True,
            )
        try:
            await observer.close()
        except Exception as exc:
            report["cleanup_errors"].append("close: {}".format(exc))
        Path("verification.local.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["cleanup_errors"]:
        raise DemoError(
            "Live test cleanup errors: " + "; ".join(report["cleanup_errors"])
        )


def main():
    parser = argparse.ArgumentParser(
        description="Live verification changes one idle zone and restores its settings."
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument(
        "--route",
        action="store_true",
        help="Authorize temporarily routing the player's input to its selected zone",
    )
    args = parser.parse_args()
    try:
        asyncio.run(verify(args))
    except (DemoError, OSError) as exc:
        print("Live verification error: {}".format(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
