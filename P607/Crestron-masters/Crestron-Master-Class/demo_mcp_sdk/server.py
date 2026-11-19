"""MCP server on the official SDK (Python 3.10+), with the same tools as demo_mcp.

Tool names, descriptions, annotations and the preview/confirm approval rules live
once, in demo_mcp/protocol.py; this file only exposes them through the SDK
(see README for the differences). A client that can be asked (MCP elicitation) is
asked to approve a change instead of being handed a token.
"""

import argparse
import asyncio
import sys
from pathlib import Path

if __package__ is None:  # run as python demo_mcp_sdk/server.py: make the repo root importable
    sys.path[0] = str(Path(__file__).resolve().parents[1])

from demo_mcp_sdk import INSTALL_HINT, available

if __name__ == "__main__" and not available():  # MCP hosts launch this file directly
    print(INSTALL_HINT, file=sys.stderr)
    sys.exit(1)

from contextlib import asynccontextmanager
from typing import Any, Callable, Literal, Optional, Union

from mcp.server import MCPServer, NotificationOptions
from mcp.server.elicitation import AcceptedElicitation
from mcp.server.mcpserver import Context
from mcp_types import CallToolResult, ListToolsResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field, StrictBool, StrictInt, StrictStr

from crestron.config import DEFAULT_CONFIG
from crestron.device import ACTIONS, SEARCH_CATEGORIES
from demo_mcp.protocol import (
    TOOL_DEFINITIONS,
    DemoMcpService,
    RpcError,
    schema_with_ids,
    tool_description,
)

SERVER_NAME = "crestron-demo-sdk"
_SPEC = {tool["name"]: tool for tool in TOOL_DEFINITIONS}
Action = Literal[tuple(ACTIONS)]  # one source for both servers' enums
Category = Literal[tuple(SEARCH_CATEGORIES)]


class Approval(BaseModel):
    """The one question put to the user: a single boolean, off unless they tick it."""

    confirm: bool = Field(False, description="Tick to go ahead with this change")


def can_ask(session) -> bool:
    """True when the client declared form elicitation and this connection can carry a
    server request (the 2026-07-28 protocol cannot, so those clients get tokens)."""
    caps = session.client_capabilities
    ask = caps.elicitation if caps is not None else None
    return ask is not None and (ask.form is not None or ask.url is None) and session.can_send_request


def build_server(device_factory: Callable[[], Any]) -> MCPServer:
    service = DemoMcpService(device_factory)

    @asynccontextmanager
    async def lifespan(server):
        try:
            yield {}
        finally:
            for player in await service.close():  # pauses playback this server started
                print("Cleanup: {} paused".format(player), file=sys.stderr)

    # The SDK runs requests concurrently; the approval gate expects one at a time.
    lock = asyncio.Lock()

    # _handle_list_tools and _lowlevel_server below are SDK internals, written for
    # the pinned mcp==2.3.0 (requirements.txt); recheck them before upgrading.
    class Server(MCPServer):
        async def _handle_list_tools(self, ctx, params):
            # Per client: its description of how changes are approved, and the
            # device's valid ids as enums (none while the device cannot be reached).
            asks = can_ask(ctx.session)
            ids = await service.listing_ids()  # not under the lock: the device may stall
            tools = []
            for tool in await self.list_tools():
                spec = _SPEC[tool.name]
                tools.append(
                    tool.model_copy(
                        update={
                            "description": tool_description(spec, asks),
                            "input_schema": schema_with_ids(tool.input_schema, ids),
                        }
                    )
                )
            return ListToolsResult(tools=tools)

    mcp = Server(SERVER_NAME, lifespan=lifespan)
    # Handshake-era clients learn from the capability that tools/list can change.
    lowlevel = mcp._lowlevel_server
    create_options = lowlevel.create_initialization_options

    def with_list_changed(notification_options=None, *args, **kwargs):
        return create_options(
            notification_options or NotificationOptions(tools_changed=True), *args, **kwargs
        )

    lowlevel.create_initialization_options = with_list_changed

    async def call(name: str, ctx: Context, **arguments: Any) -> CallToolResult:
        # Optional arguments left out by the caller stay out, as in the custom server.
        arguments = {key: value for key, value in arguments.items() if value is not None}
        approve = None
        if can_ask(ctx.session):

            async def approve(message: str) -> bool:
                reply = await ctx.elicit(message, Approval)  # no lock held while they decide
                return isinstance(reply, AcceptedElicitation) and reply.data.confirm

        try:
            raw = await service.call_tool(name, arguments, approve, lock)
        except RpcError as exc:  # the custom server answers these as protocol errors
            raw = DemoMcpService._tool_result({"error": exc.message, "tool": name}, True)
        if service.take_tools_changed():
            await ctx.session.send_tool_list_changed()  # handshake-era clients
            await ctx.notify_tools_changed()  # 2026-07-28 subscriptions/listen
        return CallToolResult(
            content=[TextContent(type="text", text=raw["content"][0]["text"])],
            structured_content=raw["structuredContent"],
            is_error=raw["isError"],
        )

    def tool(name: str):
        spec = _SPEC[name]
        return mcp.tool(
            name=name,
            description=spec["description"],
            annotations=ToolAnnotations(**spec["annotations"]),
        )

    @tool("list_profiles")
    async def list_profiles(ctx: Context) -> CallToolResult:
        return await call("list_profiles", ctx)

    @tool("list_services")
    async def list_services(ctx: Context, profile: StrictStr) -> CallToolResult:
        return await call("list_services", ctx, profile=profile)

    @tool("browse")
    async def browse(
        ctx: Context,
        profile: StrictStr,
        service: StrictStr,
        folder: Optional[StrictStr] = None,
        page: Optional[StrictStr] = None,
    ) -> CallToolResult:
        return await call(
            "browse", ctx, profile=profile, service=service, folder=folder, page=page
        )

    @tool("search")
    async def search(
        ctx: Context, profile: StrictStr, service: StrictStr, text: StrictStr, category: Category
    ) -> CallToolResult:
        return await call(
            "search", ctx, profile=profile, service=service, text=text, category=category
        )

    @tool("home_screen")
    async def home_screen(ctx: Context, profile: StrictStr) -> CallToolResult:
        return await call("home_screen", ctx, profile=profile)

    @tool("list_favorites")
    async def list_favorites(ctx: Context, profile: StrictStr) -> CallToolResult:
        return await call("list_favorites", ctx, profile=profile)

    @tool("list_players")
    async def list_players(ctx: Context) -> CallToolResult:
        return await call("list_players", ctx)

    @tool("list_zones")
    async def list_zones(ctx: Context) -> CallToolResult:
        return await call("list_zones", ctx)

    @tool("list_inputs")
    async def list_inputs(ctx: Context) -> CallToolResult:
        return await call("list_inputs", ctx)

    @tool("play_item")
    async def play_item(
        ctx: Context,
        player: StrictStr,
        item: StrictStr,
        confirm: Optional[StrictBool] = None,
        token: Optional[StrictStr] = None,
    ) -> CallToolResult:
        return await call(
            "play_item", ctx, player=player, item=item, confirm=confirm, token=token
        )

    @tool("player_action")
    async def player_action(
        ctx: Context,
        player: StrictStr,
        action: Action,
        value: Union[StrictBool, StrictInt, StrictStr, None] = None,
        confirm: Optional[StrictBool] = None,
        token: Optional[StrictStr] = None,
    ) -> CallToolResult:
        return await call(
            "player_action",
            ctx,
            player=player,
            action=action,
            value=value,
            confirm=confirm,
            token=token,
        )

    @tool("pause")
    async def pause(ctx: Context, player: StrictStr) -> CallToolResult:
        return await call("pause", ctx, player=player)

    @tool("set_volume")
    async def set_volume(
        ctx: Context,
        zone: StrictStr,
        percent: StrictInt,
        confirm: Optional[StrictBool] = None,
        token: Optional[StrictStr] = None,
    ) -> CallToolResult:
        return await call(
            "set_volume", ctx, zone=zone, percent=percent, confirm=confirm, token=token
        )

    @tool("set_mute")
    async def set_mute(
        ctx: Context,
        zone: StrictStr,
        muted: StrictBool,
        confirm: Optional[StrictBool] = None,
        token: Optional[StrictStr] = None,
    ) -> CallToolResult:
        return await call(
            "set_mute", ctx, zone=zone, muted=muted, confirm=confirm, token=token
        )

    @tool("set_route")
    async def set_route(
        ctx: Context,
        zone: StrictStr,
        input: StrictStr,
        confirm: Optional[StrictBool] = None,
        token: Optional[StrictStr] = None,
    ) -> CallToolResult:
        return await call(
            "set_route", ctx, zone=zone, input=input, confirm=confirm, token=token
        )

    return mcp


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Crestron demo MCP server (official SDK, Python 3.10+)"
    )
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG, help="Path to the local Crestron demo config JSON"
    )
    args = parser.parse_args()

    def make_device() -> Any:
        from crestron.config import load_config
        from crestron.device import Device

        return Device(load_config(args.config))

    try:
        build_server(make_device).run(transport="stdio")
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print("MCP server stopped: {}".format(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
