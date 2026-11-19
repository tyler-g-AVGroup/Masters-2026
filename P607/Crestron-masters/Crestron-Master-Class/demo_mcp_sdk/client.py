"""Run the demo through the official-SDK MCP server: python demo_mcp_sdk/client.py"""

import sys
from pathlib import Path

if __package__ is None:  # run as python demo_mcp_sdk/client.py: make the repo root importable
    sys.path[0] = str(Path(__file__).resolve().parents[1])

from demo_mcp_sdk import INSTALL_HINT, available


def main():
    if not available():
        print(INSTALL_HINT, file=sys.stderr)
        return 1
    from demo_mcp.client import main as run

    return run("demo_mcp_sdk.server")


if __name__ == "__main__":
    sys.exit(main())
