"""MCP demo on the official MCP Python SDK (Python 3.10+)."""

import importlib.util
import sys

INSTALL_HINT = (
    "The official-SDK MCP demo needs Python 3.10+ and: pip install -r requirements.txt\n"
    "Without them use: python demo_mcp/client.py"
)


def available():
    """True when this interpreter can run the SDK server (plain 3.8 syntax on purpose)."""
    # mcp_types ships only with the 2.x SDK this server is written for.
    return (
        sys.version_info >= (3, 10)
        and importlib.util.find_spec("mcp_types") is not None
    )
