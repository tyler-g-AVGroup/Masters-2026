"""Minimal MCP 2025-11-25 JSON-RPC support and the device tools all three servers share
(demo_mcp stdio, demo_mcp_sdk and demo_mcp_http)."""

from __future__ import annotations

import asyncio
import json
import math
import secrets
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from crestron.device import ACTIONS, SEARCH_CATEGORIES

PROTOCOL_VERSION = "2025-11-25"
SERVER_INFO = {"name": "crestron-demo", "version": "0.2.0"}

_READ = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
_CHANGE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": False,
}
_APPROVAL = (
    " Call it first without confirm: it changes nothing and returns a preview and a"
    " token. Show the preview to the user; only after they approve, call again with"
    " the same arguments plus confirm=true and the token."
)
# Offered instead of _APPROVAL where the server can ask the user through the client.
_APPROVAL_ASK = (
    " The user is asked to approve it in their client: call it once, without confirm or"
    " token, and wait; the result says it was done or 'Not changed'. If you get a"
    " preview and a token instead, show the preview to the user; only after they"
    " approve, call again with the same arguments plus confirm=true and the token."
)
_STR = {"type": "string"}
_GATE = {"confirm": {"type": "boolean"}, "token": _STR}


def _tool(name, description, properties=None, required=(), annotations=_READ):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties or {},
            "required": list(required),
            "additionalProperties": False,
        },
        "annotations": dict(annotations),
    }


TOOL_DEFINITIONS = [
    _tool("list_profiles", "List the device's user profiles. Start here."),
    _tool(
        "list_services",
        "List the streaming services of a profile, with their sign-in state.",
        {"profile": _STR},
        ["profile"],
    ),
    _tool(
        "browse",
        "List a service's menu: its root, a folder (folder = an item id), or the next"
        " page (page = a next_page id). Items have ids; playable ones go to play_item.",
        {"profile": _STR, "service": _STR, "folder": _STR, "page": _STR},
        ["profile", "service"],
    ),
    _tool(
        "search",
        "Search one service. One category per call. Album, artist and playlist hits"
        " are folders to browse; song and station hits are playable.",
        {
            "profile": _STR,
            "service": _STR,
            "text": _STR,
            "category": {
                "type": "string",
                "enum": list(SEARCH_CATEGORIES),
            },
        },
        ["profile", "service", "text", "category"],
    ),
    _tool(
        "home_screen",
        "List the profile's home screen (for example recently played).",
        {"profile": _STR},
        ["profile"],
    ),
    _tool(
        "list_favorites",
        "List the profile's favorites; playable ones go to play_item.",
        {"profile": _STR},
        ["profile"],
    ),
    _tool(
        "list_players",
        "List active players: state, what is playing, the actions they offer now,"
        " and the zones that hear them.",
    ),
    _tool(
        "list_zones",
        "List zones: volume and limits in percent, mute, grouped, and the routed source.",
    ),
    _tool("list_inputs", "List the device's inputs, including media player inputs."),
    _tool(
        "play_item",
        "Play a song or station (an item id from browse, search, home or favorites)"
        " on a player." + _APPROVAL,
        dict(player=_STR, item=_STR, **_GATE),
        ["player", "item"],
        _CHANGE,
    ),
    _tool(
        "player_action",
        "Control a player: play (resume), next, previous, seek (value = seconds),"
        " forward or rewind (15 s), shuffle (value = true/false), repeat (value ="
        " off/track/list). Only actions the player offers now are accepted." + _APPROVAL,
        dict(
            player=_STR,
            action={"type": "string", "enum": list(ACTIONS)},
            value={"type": ["integer", "boolean", "string"]},
            **_GATE
        ),
        ["player", "action"],
        _CHANGE,
    ),
    _tool(
        "pause",
        "Pause a player. Needs no approval: stopping sound is always allowed.",
        {"player": _STR},
        ["player"],
        dict(_CHANGE, destructiveHint=False, idempotentHint=True),
    ),
    _tool(
        "set_volume",
        "Set a zone's volume in percent, within the zone's limits." + _APPROVAL,
        dict(zone=_STR, percent={"type": "integer"}, **_GATE),
        ["zone", "percent"],
        _CHANGE,
    ),
    _tool(
        "set_mute",
        "Mute or unmute a zone." + _APPROVAL,
        dict(zone=_STR, muted={"type": "boolean"}, **_GATE),
        ["zone", "muted"],
        _CHANGE,
    ),
    _tool(
        "set_route",
        "Route an input to a zone (input = an input key, or an empty string for none)."
        + _APPROVAL,
        dict(zone=_STR, input=_STR, **_GATE),
        ["zone", "input"],
        _CHANGE,
    ),
]
_SCHEMAS = {tool["name"]: tool["inputSchema"] for tool in TOOL_DEFINITIONS}
_GATED = {"play_item", "player_action", "set_volume", "set_mute", "set_route"}
_APPROVAL_TTL_SECONDS = 120
_LISTING_SECONDS = 10  # tools/list waits this long for the device, then lists without ids
# Argument -> the read tool that lists its valid ids, and the key of that list.
_ID_SOURCES = {
    "profile": ("list_profiles", "profiles"),
    "player": ("list_players", "players"),
    "zone": ("list_zones", "zones"),
    "input": ("list_inputs", "inputs"),
}
_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: type(v) is int,
    "boolean": lambda v: type(v) is bool,
}


class RpcError(Exception):
    """A JSON-RPC error with a standard error code."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class ToolFailure(Exception):
    """A rejected or failed tool execution represented by an MCP tool result."""

    def __init__(self, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.data = data


def check_arguments(name: str, arguments: Dict[str, Any]) -> None:
    """Validate arguments against the tool's own inputSchema (the one source)."""
    schema = _SCHEMAS[name]
    properties = schema["properties"]
    unexpected = sorted(set(arguments) - set(properties))
    missing = [key for key in schema["required"] if key not in arguments]
    if unexpected or missing:
        raise RpcError(
            -32602,
            "Invalid params for {}".format(name),
            {"unexpected": unexpected, "missing": missing},
        )
    for key, value in arguments.items():
        spec = properties[key]
        types = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
        if not any(_TYPES[kind](value) for kind in types) or (
            "enum" in spec and value not in spec["enum"]
        ):
            raise RpcError(
                -32602, "Invalid params for {}: bad {}".format(name, key)
            )


def _id_map(arg: str, result: Dict[str, Any]) -> Dict[str, str]:
    """{id: name} from a list_* result; set_route also accepts '' (no input)."""
    entries = result[_ID_SOURCES[arg][1]]
    ids = {entry[arg]: entry.get("name") or "" for entry in entries}
    return dict({"": "none"}, **ids) if arg == "input" else ids


def schema_with_ids(schema: Dict[str, Any], ids: Optional[Dict[str, Dict[str, str]]]) -> Dict[str, Any]:
    """A copy of a tool's inputSchema with the device's valid ids as enum and in the
    description. The shared schemas stay as they are: a stale list must not become
    a protocol error, the device check gives the friendly one."""
    properties = dict(schema["properties"])
    for arg, names in (ids or {}).items():
        if arg in properties and names:  # new dicts: _STR is shared by many arguments
            properties[arg] = dict(
                properties[arg],
                enum=list(names),
                description="; ".join(
                    "{} = {}".format(key or "''", name) if name else key
                    for key, name in names.items()
                ),
            )
    return dict(schema, properties=properties)


def tool_description(spec: Dict[str, Any], asks: bool = False) -> str:
    """The tool's description; asks = the client will be asked to approve changes."""
    return spec["description"].replace(_APPROVAL, _APPROVAL_ASK) if asks else spec["description"]


class _Unlocked:
    """Stands in for the lock where requests are already handled one at a time."""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: Any) -> None:
        return None


class DemoMcpService:
    """Protocol dispatcher, tool routing and the preview/confirm approval gate."""

    def __init__(self, device_factory: Callable[[], Any]) -> None:
        self._device_factory = device_factory
        self._device: Any = None
        self._initialized = False
        self._approvals: Dict[str, Dict[str, Any]] = {}
        self._advertised: Optional[Dict[str, Dict[str, str]]] = None  # ids in the last tools/list
        self._listing_tasks: Set["asyncio.Future[Any]"] = set()  # discovery reads still winding down
        self._tools_changed = False

    def _device_instance(self) -> Any:
        if self._device is None:
            self._device = self._device_factory()
        return self._device

    async def close(self) -> List[str]:
        """Pause playback this server started (if still ours); return those players."""
        # Listing reads still running (cancelled, or past their deadline) may be
        # mid-connect or mid-login: let them finish first, so what they open is
        # closed with the rest and nothing is installed after the device closed.
        tasks = list(self._listing_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        device, self._device = self._device, None
        return (await device.close() or []) if device is not None else []

    async def listing_ids(self) -> Optional[Dict[str, Dict[str, str]]]:
        """The device's valid ids for tools/list, or None when it cannot be reached.
        Takes no tool lock: it must not hold other calls up while the device stalls."""

        async def fetch() -> Dict[str, Dict[str, str]]:
            device = self._device_instance()
            return {
                arg: _id_map(arg, await self._read(device, tool, {}))
                for arg, (tool, _) in _ID_SOURCES.items()
            }

        # Not wait_for: it waits for the cancelled read to finish, and a stalled REST
        # read (RestClient._serial) only ends with its socket timeout. Give up on the
        # task at the deadline instead; it winds down on its own.
        task = asyncio.ensure_future(fetch())
        self._listing_tasks.add(task)

        def finished(done: Any) -> None:
            self._listing_tasks.discard(done)
            done.cancelled() or done.exception()  # no "never retrieved"

        task.add_done_callback(finished)
        try:
            await asyncio.wait([task], timeout=_LISTING_SECONDS)
        except asyncio.CancelledError:  # tools/list itself was cancelled
            task.cancel()
            raise
        if task.done() and not task.cancelled() and task.exception() is None:
            ids = task.result()
        else:  # unreachable, timed out, refused: list without ids, no error
            task.cancel()
            ids = None
        self._advertised = ids or {}
        return ids

    async def tool_list(self) -> List[Dict[str, Any]]:
        ids = await self.listing_ids()
        return [
            dict(tool, inputSchema=schema_with_ids(tool["inputSchema"], ids))
            for tool in TOOL_DEFINITIONS
        ]

    def take_tools_changed(self) -> bool:
        """True once after the valid ids changed since the last tools/list."""
        changed, self._tools_changed = self._tools_changed, False
        return changed

    def _note_ids(self, name: str, result: Dict[str, Any]) -> None:
        for arg, (tool, _) in _ID_SOURCES.items():
            if tool == name and self._advertised is not None:  # a list_* tool, after a listing
                ids = _id_map(arg, result)
                if self._advertised.get(arg) != ids:
                    self._advertised[arg] = ids
                    self._tools_changed = True

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RpcError(-32002, "Server is not initialized")

    @staticmethod
    def _tool_result(value: Dict[str, Any], is_error: bool = False) -> Dict[str, Any]:
        # structuredContent is convenient for protocol clients; text keeps the
        # result useful in clients that render only unstructured content.
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(value, ensure_ascii=False, sort_keys=True),
                }
            ],
            "structuredContent": value,
            "isError": is_error,
        }

    async def _read(self, device: Any, name: str, args: Dict[str, Any]) -> Any:
        if name == "list_profiles":
            return await device.profiles()
        if name == "list_services":
            return await device.services(args["profile"])
        if name == "browse":
            return await device.browse(
                args["profile"], args["service"], args.get("folder"), args.get("page")
            )
        if name == "search":
            return await device.search(
                args["profile"], args["service"], args["text"], args["category"]
            )
        if name == "home_screen":
            return await device.home(args["profile"])
        if name == "list_favorites":
            return await device.favorites(args["profile"])
        if name == "list_players":
            return await device.players()
        if name == "list_zones":
            return await device.zones()
        if name == "list_inputs":
            return await device.inputs()
        # pause: the one change outside the approval gate (stopping sound is always allowed).
        return await device.pause(args["player"])

    def _drop_expired(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self._approvals.items() if v["expires"] < now]:
            del self._approvals[key]

    def _issue_token(
        self, name: str, args: Dict[str, Any], preview: Any, fingerprint: str
    ) -> Dict[str, Any]:
        token = secrets.token_urlsafe(16)
        self._approvals[token] = {
            "tool": name,
            "args": args,
            "fingerprint": fingerprint,
            "expires": time.monotonic() + _APPROVAL_TTL_SECONDS,
        }
        return {
            "preview": preview,
            "token": token,
            "expires_in_seconds": _APPROVAL_TTL_SECONDS,
            "next": "Show this preview to the user. Only after they approve, call"
            " {} again with the same arguments plus confirm=true and this"
            " token.".format(name),
        }

    async def _gated(
        self,
        device: Any,
        name: str,
        args: Dict[str, Any],
        elicit: Optional[Callable[[str], Awaitable[bool]]],
        lock: Any,
    ) -> Any:
        """Each device step runs under the lock; waiting for the user does not."""
        confirm = args.pop("confirm", False)
        token = args.pop("token", None)
        if not confirm:
            if token is not None:
                raise ToolFailure("A token is only used together with confirm=true.")
            async with lock:
                self._drop_expired()
                preview, fingerprint = await device.preview(name, args)
                if elicit is None:
                    return self._issue_token(name, args, preview, fingerprint)
            message = "{}. Go ahead?".format(
                preview.get("change") or "{} {}".format(name, args)
            )
            try:
                approved = await asyncio.wait_for(elicit(message), _APPROVAL_TTL_SECONDS)
            except asyncio.TimeoutError:
                return "Not changed: no answer within {} seconds.".format(
                    _APPROVAL_TTL_SECONDS
                )
            except Exception:  # the client could not be asked: use the token
                async with lock:
                    return self._issue_token(name, args, preview, fingerprint)
            if not approved:
                return "Not changed: the user declined."
            async with lock:
                return await self._apply(device, name, args, fingerprint)
        async with lock:
            self._drop_expired()
            approval = self._approvals.pop(token, None) if isinstance(token, str) else None
            if approval is None or approval["tool"] != name or approval["args"] != args:
                raise ToolFailure(
                    "Missing, expired or mismatched approval token; call without confirm"
                    " to preview again."
                )
            return await self._apply(device, name, args, approval["fingerprint"])

    @staticmethod
    async def _apply(device: Any, name: str, args: Dict[str, Any], shown: str) -> Any:
        """Make the approved change if the device still matches what was previewed."""
        preview, fingerprint = await device.preview(name, args)
        if fingerprint != shown:
            raise ToolFailure(
                "The device changed since the preview; show the new preview and ask again.",
                {"preview": preview},
            )
        try:
            return await device.change(name, args)
        except Exception as exc:
            raise ToolFailure(
                "{} The change may or may not have applied; read the state back.".format(
                    str(exc) or exc.__class__.__name__
                )
            )

    async def call_tool(
        self,
        name: Any,
        arguments: Any,
        elicit: Optional[Callable[[str], Awaitable[bool]]] = None,
        lock: Any = None,
    ) -> Dict[str, Any]:
        """elicit(message) asks the user and returns whether they approved; with it a
        change needs no token. Without it the preview and token flow applies.
        lock (an async context manager) serializes device work; it is not held while
        the user is being asked."""
        lock = lock if lock is not None else _Unlocked()
        if not isinstance(name, str):
            raise RpcError(-32602, "Invalid params: tool name must be a string")
        if not isinstance(arguments, dict):
            raise RpcError(-32602, "Invalid params: arguments must be an object")
        if name not in _SCHEMAS:
            raise RpcError(-32602, "Unknown tool", {"name": name})
        check_arguments(name, arguments)
        args = dict(arguments)
        try:
            device = self._device_instance()
            if name in _GATED:
                result = await self._gated(device, name, args, elicit, lock)
            else:
                async with lock:
                    result = await self._read(device, name, args)
                    self._note_ids(name, result)
            return self._tool_result(
                result if isinstance(result, dict) else {"result": result}
            )
        except ToolFailure as exc:
            failure = {"error": str(exc), "tool": name}
            if exc.data is not None:
                failure["details"] = exc.data
            return self._tool_result(failure, is_error=True)
        except RpcError:
            raise
        except Exception as exc:
            # Keep device failures honest without exposing tracebacks or credentials.
            return self._tool_result(
                {"error": str(exc) or exc.__class__.__name__, "tool": name},
                is_error=True,
            )

    async def dispatch(self, message: Any, lock: Any = None) -> Optional[Dict[str, Any]]:
        """Dispatch a message; HTTP sessions may share a device-operation lock."""
        if not isinstance(message, dict):
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid Request"},
            }
        request_id = message.get("id")
        has_id = "id" in message
        valid_id = request_id is None or (
            isinstance(request_id, (str, int, float))
            and not isinstance(request_id, bool)
            and (not isinstance(request_id, float) or math.isfinite(request_id))
        )
        if (
            message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)
            or (has_id and not valid_id)
        ):
            return {
                "jsonrpc": "2.0",
                "id": request_id if has_id and valid_id else None,
                "error": {"code": -32600, "message": "Invalid Request"},
            }
        method = message["method"]
        if method == "tools/call" and not has_id:
            # JSON-RPC notifications have no response channel and must never
            # cause a side effect whose result the caller cannot observe.
            return None
        params = message.get("params", {})
        if not isinstance(params, dict):
            return {
                "jsonrpc": "2.0",
                "id": request_id if has_id else None,
                "error": {"code": -32602, "message": "Invalid params"},
            }
        try:
            if method == "initialize":
                if not has_id:
                    raise RpcError(-32600, "initialize must be a request")
                version = params.get("protocolVersion")
                if version != PROTOCOL_VERSION:
                    raise RpcError(
                        -32602,
                        "Unsupported protocol version",
                        {"supported": [PROTOCOL_VERSION]},
                    )
                if not isinstance(params.get("clientInfo"), dict):
                    raise RpcError(-32602, "initialize requires clientInfo")
                self._initialized = True
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": SERVER_INFO,
                }
            elif method == "notifications/initialized":
                if has_id:
                    raise RpcError(-32600, "Notifications must not include an id")
                # Valid notification receives no JSON-RPC response.
                return None
            elif method == "ping":
                result = {}
            else:
                self._require_initialized()
                if method == "tools/list":
                    result = {"tools": await self.tool_list()}
                elif method == "tools/call":
                    result = await self.call_tool(
                        params.get("name"), params.get("arguments", {}), lock=lock
                    )
                elif method == "notifications/cancelled":
                    if has_id:
                        raise RpcError(-32600, "Notifications must not include an id")
                    return None
                else:
                    raise RpcError(-32601, "Method not found")
            if not has_id:
                return None
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RpcError as exc:
            if not has_id:
                return None
            error = {"code": exc.code, "message": exc.message}
            if exc.data is not None:
                error["data"] = exc.data
            return {"jsonrpc": "2.0", "id": request_id, "error": error}
