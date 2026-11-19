"""Media Player 2.0 over WebSocket: wss://<host>/subscriptionmgr.

Login: the CrestronAuth-SHA256 HMAC in the Authorization header (or, for browsers,
in Sec-WebSocket-Protocol as "CrestronAuth-SHA256.<credentials>").
Requests: {"Device": {"<CommandSet>": {"RequestAction": {...}}}} for the command sets
SubscriptionMgr, MediaPlayerNeXt, MediaNavigation and MediaFavorites.
Replies and pushes: JSON documents shaped like the device object they describe.
"""

import asyncio
import base64
import hashlib
import hmac
import itertools
import json
import time
import uuid

from aiohttp import WSMsgType, web

from device_model import nest

AUTH_SCHEME = "CrestronAuth-SHA256"
CLOCK_SKEW = 300  # seconds a signature's timestamp may differ from ours


def parse_documents(frame):
    """One frame may hold several JSON documents back to back."""
    decoder, offset, documents = json.JSONDecoder(), 0, []
    while offset < len(frame):
        while offset < len(frame) and frame[offset].isspace():
            offset += 1
        if offset == len(frame):
            break
        value, offset = decoder.raw_decode(frame, offset)
        documents.append(value)
    return documents


class Connection:
    ids = itertools.count(1)

    def __init__(self, ws, hub, peer):
        self.id = "WsConnection{}".format(next(self.ids))
        self.ws, self.hub, self.peer = ws, hub, peer
        self.sessions = set()
        self.outbox = asyncio.Queue()
        self.writer = asyncio.ensure_future(self._write())

    def send(self, document):
        self.outbox.put_nowait(document)

    async def _write(self):
        # One writer per connection keeps replies and pushes in order.
        while True:
            document = await self.outbox.get()
            delay = self.hub.device.faults.get("reply_delay") or 0
            if delay:
                await asyncio.sleep(float(delay))
            if self.ws.closed:
                return
            try:
                await self.ws.send_str(json.dumps(document))
            except (ConnectionError, RuntimeError):
                return


class Session:
    def __init__(self, session_id, label, connection):
        self.id, self.label, self.connection = session_id, label, connection
        self.subscriptions = []


class Mp2Hub:
    def __init__(self, device, client_id, client_secret):
        self.device = device
        self.client_id = client_id
        self.secret = base64.b64decode(client_secret)
        self.connections = {}
        self.sessions = {}
        self.nonces = {}  # nonce -> time seen, to refuse a replayed login
        device.listeners.append(self.on_publish)

    # --- login ---------------------------------------------------------------------------

    def _check_credentials(self, credentials, uri):
        try:
            client_id, signature, nonce, timestamp = (
                base64.b64decode(credentials).decode().split(":"))
            age = abs(time.time() - int(timestamp))
        except (ValueError, UnicodeDecodeError):
            return "malformed credentials"
        if not hmac.compare_digest(client_id, self.client_id):
            return "unknown client_id"
        if age > CLOCK_SKEW:
            return "timestamp is {:.0f} s off; sync the clock".format(age)
        source = (client_id + "GET" + uri + timestamp + nonce).encode()
        expected = base64.b64encode(hmac.new(self.secret, source, hashlib.sha256).digest())
        if not hmac.compare_digest(expected.decode(), signature):
            return "bad signature (wrong client_secret, or the URL signed is not " + uri + ")"
        now = time.time()
        self.nonces = {n: t for n, t in self.nonces.items() if now - t < CLOCK_SKEW}
        if nonce in self.nonces:
            return "nonce already used"
        self.nonces[nonce] = now
        return None

    def _login(self, request):
        """(error or None, the subprotocol to echo or None)."""
        if self.device.faults.get("reject_mp2_login"):
            return "reject_mp2_login fault is on", None
        uri = "wss://{}{}".format(request.host, request.path)
        header = request.headers.get("Authorization", "")
        if header.startswith(AUTH_SCHEME + " "):
            return self._check_credentials(header[len(AUTH_SCHEME) + 1:].strip(), uri), None
        for protocol in request.headers.get("Sec-WebSocket-Protocol", "").split(","):
            protocol = protocol.strip()
            if protocol.startswith(AUTH_SCHEME + "."):
                return self._check_credentials(protocol[len(AUTH_SCHEME) + 1:], uri), protocol
        return "no {} credentials".format(AUTH_SCHEME), None

    async def handle(self, request):
        error, protocol = self._login(request)
        if error:
            self.device.log("MP2", "login refused from {}: {}".format(request.remote, error))
            return web.Response(status=401, text="Unauthorized: " + error)
        ws = web.WebSocketResponse(protocols=(protocol,) if protocol else (),
                                   max_msg_size=8 * 1024 * 1024)
        await ws.prepare(request)
        connection = Connection(ws, self, request.remote)
        self.connections[connection.id] = connection
        self.device.log("MP2", "{} opened from {}".format(connection.id, request.remote))
        try:
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    continue
                try:
                    documents = parse_documents(message.data)
                except ValueError:
                    connection.send(self._error("Request is not valid JSON"))
                    continue
                for document in documents:
                    self.dispatch(connection, document)
        finally:
            connection.writer.cancel()
            for session_id in connection.sessions:
                self.sessions.pop(session_id, None)
            self.connections.pop(connection.id, None)
            self.device.log("MP2", "{} closed".format(connection.id))
        return ws

    async def drop_all(self):
        """Fault: close every WebSocket, as a reboot or network drop would."""
        for connection in list(self.connections.values()):
            await connection.ws.close(code=1001, message=b"dmnax-server dropped the connection")

    # --- dispatch ------------------------------------------------------------------------

    @staticmethod
    def _error(message, **extra):
        return {"Device": {"SubscriptionMgr": {"Error": dict(extra, Msg=message)}}}

    def dispatch(self, connection, document):
        device = document.get("Device") if isinstance(document, dict) else None
        if not isinstance(device, dict) or not device:
            connection.send(self._error("Expected {\"Device\": {\"<CommandSet>\": ...}}"))
            return
        for command_set, body in device.items():
            action = body.get("RequestAction") if isinstance(body, dict) else None
            if not isinstance(action, dict):
                connection.send(self._error("Missing RequestAction", CommandSet=command_set))
                continue
            handler = getattr(self, "_" + command_set, None)
            if handler is None:
                connection.send(self._error("Unknown command set", CommandSet=command_set))
                continue
            handler(connection, action)

    def _session(self, connection, session_id):
        session = self.sessions.get(session_id)
        if session is None or session.connection is not connection:
            connection.send(self._error("INVALID_RC_SESSION_ID", RcSessionId=session_id))
            return None
        return session

    # --- SubscriptionMgr -----------------------------------------------------------------

    def _SubscriptionMgr(self, connection, action):
        name = action.get("RegistrationAction")
        options = action.get("RegistrationActionOptions") or {}
        if name == "RegisterClient":
            labels = options.get("RegisteringClientIds") or []
            for label in labels if isinstance(labels, list) else [labels]:
                session = Session("RC" + uuid.uuid4().hex[:16], str(label), connection)
                self.sessions[session.id] = session
                connection.sessions.add(session.id)
                self.device.log("MP2", "registered '{}' as {}".format(label, session.id))
            listed = {sid: {"RegisteredClientId": self.sessions[sid].label}
                      for sid in connection.sessions}
            connection.send({"Device": {"SubscriptionMgr": {
                "ConnectedClientWsCount": len(self.connections),
                "WsConnectionsList": {connection.id: {"RegisteredClientList": listed}}}}})
            return
        session = self._session(connection, options.get("RcSessionId"))
        if session is None:
            return
        if name == "GetCresNextObject":
            path = options.get("CresNextObject")
            value = self.device.read(path)
            if path == "/Device/SubscriptionMgr":
                value = self._manager_object()
            if value is None:
                connection.send(self._error("Invalid CresNextObject path", CresNextObject=path))
            else:
                connection.send(nest(path, value))
        elif name in ("SubscribeToObject", "UnsubscribeFromObject", "UnsubscribeToObject"):
            paths = options.get("CresNextPath") or []
            paths = paths if isinstance(paths, list) else [paths]
            for path in paths:
                if not isinstance(path, str) or not path.startswith("/Device/"):
                    continue
                if name == "SubscribeToObject" and path not in session.subscriptions:
                    session.subscriptions.append(path)
                elif name != "SubscribeToObject" and path in session.subscriptions:
                    session.subscriptions.remove(path)
            self.device.log("MP2", "{} {} {} path(s)".format(
                session.id, "subscribed to" if name == "SubscribeToObject" else "unsubscribed from",
                len(paths)))
            connection.send({"Device": {"SubscriptionMgr": {"RegisteredClientList": {
                session.id: {"SubscribedTo": {
                    str(index): {"CresNextPath": path}
                    for index, path in enumerate(session.subscriptions, 1)}}}}}})
        elif name == "UnregisterClient":
            self.sessions.pop(session.id, None)
            connection.sessions.discard(session.id)
            connection.send({"Device": {"SubscriptionMgr": {"RegisteredClientList": {
                session.id: {}}}}})
        else:
            connection.send(self._error("Unknown RegistrationAction", RegistrationAction=name))

    def _manager_object(self):
        return {
            "ConnectedClientWsCount": len(self.connections),
            "ExpirationDurInSecs": 1200,
            "WsConnectionsList": {
                cid: {"RegisteredClientList": {
                    sid: {"RegisteredClientId": self.sessions[sid].label}
                    for sid in c.sessions if sid in self.sessions}}
                for cid, c in self.connections.items()
            },
        }

    def on_publish(self, path, delta):
        """Forward a device change to every connection with a matching subscription."""
        document = nest(path, delta)
        for connection in list(self.connections.values()):
            for session_id in connection.sessions:
                session = self.sessions.get(session_id)
                if session and any(path == sub or path.startswith(sub.rstrip("/") + "/")
                                   for sub in session.subscriptions):
                    connection.send(document)
                    break

    # --- MediaPlayerNeXt -----------------------------------------------------------------

    def _MediaPlayerNeXt(self, connection, action):
        if self._session(connection, action.get("RcSessionId")) is None:
            return
        player, name = action.get("PlayerId"), action.get("ActionId")
        if name != "Notification":
            self.device.log("MP2", "{} <- {}".format(player, name))
        error = self.device.player_action(player, name, action.get("ActionIdOptions"))
        if error:
            connection.send(self._error(error, PlayerId=player))

    # --- MediaNavigation -----------------------------------------------------------------

    def _MediaNavigation(self, connection, action):
        session = self._session(connection, action.get("RcSessionId"))
        if session is None:
            return
        category = action.get("MenuCategory")
        options = action.get("MenuCategoryOptions") or {}
        menu, refusal = self.device.catalog.navigate(action.get("ProfileKey"), category, options)
        node = {"LastRequestAction": {"MsgId": action.get("MsgId"), "MenuCategory": category}}
        if refusal:
            self.device.notice_id += 1
            node["Notification"] = {"NotiId": self.device.notice_id, "Msg": refusal,
                                    "UserInputReq": "None", "UserInputs": {"Input1": "OK"}}
            self.device.log("MP2", "{} refused: {}".format(category, refusal))
        else:
            node["MenuUpdates"] = {category: menu}
            what = options.get("SearchText") or options.get("BrowseKey") or ""
            self.device.log("MP2", "{} {} (offset {})".format(category, what,
                                                              options.get("ItemOffset", 0)))
        connection.send(nest("/Device/MediaNavigation/RegisteredClientMenus/" + session.id, node))

    # --- MediaFavorites ------------------------------------------------------------------

    def _MediaFavorites(self, connection, action):
        if self._session(connection, action.get("RcSessionId")) is None:
            return
        profile = action.get("ProfileKey")
        path = "/Device/MediaFavorites/Profiles/{}".format(profile)
        name = action.get("FavoritesAction")
        if profile not in self.device.catalog.favorites:
            message = "Unknown ProfileKey '{}'".format(profile)
        elif name == "ListFavorites":
            entries = self.device.catalog.favorites_list(profile)
            self.device.log("MP2", "ListFavorites {}: {} item(s)".format(profile, len(entries)))
            connection.send(nest(path, {"Favorites": entries}))
            return
        elif name == "Notification":
            connection.send(nest(path, {"Notification": {}}))
            return
        else:
            message = "FavoritesAction '{}' is not supported by dmnax-server".format(name)
        self.device.notice_id += 1
        connection.send(nest(path, {"Notification": {
            "NotiId": self.device.notice_id, "Msg": message, "UserInputs": {"Input1": "OK"}}}))
