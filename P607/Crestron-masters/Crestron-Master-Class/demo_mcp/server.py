"""MCP stdio server: python demo_mcp/server.py (an MCP host launches it)."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

if __package__ is None:  # run as python demo_mcp/server.py: make the repo root importable
    sys.path[0] = str(Path(__file__).resolve().parents[1])
from typing import Any

from crestron.config import DEFAULT_CONFIG
from demo_mcp.protocol import DemoMcpService


async def serve_stdio(config_path: str) -> None:
    """Serve one MCP client over newline-delimited JSON-RPC stdio."""

    def make_device() -> Any:
        from crestron.config import load_config
        from crestron.device import Device

        return Device(load_config(config_path))

    service = DemoMcpService(make_device)
    loop = asyncio.get_running_loop()
    try:
        while True:
            # A thread reads stdin, so this works the same on Windows.
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if line == "":
                break
            try:
                message = json.loads(line)
            except (ValueError, TypeError):
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                }
            else:
                response = await service.dispatch(message)
            messages = [response] if response is not None else []
            if service.take_tools_changed():  # the client re-reads tools/list
                messages.append(
                    {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
                )
            for out in messages:
                sys.stdout.write(
                    json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
                sys.stdout.flush()
    finally:
        for player in await service.close():  # stderr: stdout carries only protocol
            print("Cleanup: {} paused".format(player), file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Crestron demo MCP stdio server")
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG, help="Path to the local Crestron demo config JSON"
    )
    args = parser.parse_args()
    try:
        asyncio.run(serve_stdio(args.config))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print("MCP server stopped: {}".format(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
