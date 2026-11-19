"""One MP2 WebSocket session, one receive loop, and matched replies."""

import asyncio
import base64
import hashlib
import hmac
import json
import time
import uuid
from collections import deque

from websockets.exceptions import InvalidHandshake, ConnectionClosed
from websockets.legacy.client import connect

from .errors import DemoError
from .state import PlayerState, at_path, parse_messages, text


def notice_text(notification):
    if not isinstance(notification, dict):
        return str(notification)
    widget = notification.get("Widget")
    return (
        notification.get("Msg")
        or (widget.get("Msg") if isinstance(widget, dict) else None)
        or "device notification"
    )


def auth_header(config, uri):
    nonce, timestamp = str(uuid.uuid4()), str(int(time.time()))
    source = (config.client_id + "GET" + uri + timestamp + nonce).encode()
    signature = base64.b64encode(
        hmac.new(
            base64.b64decode(config.client_secret), source, hashlib.sha256
        ).digest()
    ).decode()
    credentials = "{}:{}:{}:{}".format(config.client_id, signature, nonce, timestamp)
    return "CrestronAuth-SHA256 " + base64.b64encode(credentials.encode()).decode()


class Mp2Client:
    def __init__(self, config):
        self.config = config
        self.socket = None
        self.receiver = None
        self.session = None
        self.players = {}
        self.sequence = 0
        self.history = deque(maxlen=300)
        self.changed = asyncio.Event()
        self.pending = []
        self.request_lock = asyncio.Lock()
        self.send_lock = asyncio.Lock()
        self.last_send = 0.0
        self.failure = None
        self.snapshot_paths = {}  # path -> reads outstanding (overlapping reads share a path)

    async def open(self):
        if self.socket:
            return
        uri = "wss://{}/subscriptionmgr".format(self.config.device_ip)
        for attempt in range(2):
            try:
                self.socket = await connect(
                    uri,
                    ssl=self.config.tls_context(),
                    extra_headers={"Authorization": auth_header(self.config, uri)},
                    open_timeout=10,
                    close_timeout=2,
                    max_size=8 * 1024 * 1024,
                )
                break
            except InvalidHandshake as exc:
                raise DemoError(
                    "MP2 login/handshake refused: check client_id, client_secret, and MP2 mode."
                ) from exc
            except (OSError, asyncio.TimeoutError) as exc:
                if attempt:
                    raise DemoError(
                        "MP2 device unreachable: check the address, network, and MP2 mode."
                    ) from exc
                # One retry, 10 s later: a connection opened right after another closed
                # can fail (skill crestron-mediaplayer-2, references/api-gotchas.md).
                await asyncio.sleep(10)
        self.receiver = asyncio.create_task(self._receive())
        label = "python-demo-" + str(uuid.uuid4())

        def registration(document):
            manager = at_path(document, "/Device/SubscriptionMgr") or {}
            for connection in manager.get("WsConnectionsList", {}).values():
                for session, client in connection.get(
                    "RegisteredClientList", {}
                ).items():
                    if client.get("RegisteredClientId") == label:
                        return session
            return None

        reply = await self._query(
            "SubscriptionMgr",
            {
                "RegistrationAction": "RegisterClient",
                "RegistrationActionOptions": {"RegisteringClientIds": [label]},
            },
            registration,
        )
        self.session = registration(reply)

    async def _receive(self):
        try:
            async for frame in self.socket:
                for document in parse_messages(frame):
                    self.sequence += 1
                    self.history.append((self.sequence, document))
                    updates = at_path(document, "/Device/MediaPlayerNeXt/Players") or {}
                    is_snapshot = any(
                        at_path(document, path) is not None
                        for path in self.snapshot_paths
                    )
                    for key, delta in updates.items():
                        if isinstance(delta, dict):
                            self.players.setdefault(key, PlayerState()).update(
                                delta, pushed=not is_snapshot
                            )
                    for predicate, future in list(self.pending):
                        if not future.done() and predicate(document):
                            future.set_result(document)
                    self.changed.set()
            raise DemoError("MP2 connection closed; playback may still be active.")
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self.failure = DemoError(
                "MP2 connection lost: {}. Read device state before retrying playback.".format(
                    str(exc).rstrip(".")
                )
            )
            for _, future in self.pending:
                if not future.done():
                    future.set_exception(self.failure)
            self.changed.set()

    async def _send(self, command_set, action):
        if self.failure:
            raise self.failure
        async with self.send_lock:
            # About 100 ms between requests: two sent within ~1 ms were dropped (seen once).
            await asyncio.sleep(max(0, 0.1 - (time.monotonic() - self.last_send)))
            request = dict(action)
            request.setdefault("MsgId", str(uuid.uuid1()))  # navigate sets its own
            try:
                await self.socket.send(
                    json.dumps({"Device": {command_set: {"RequestAction": request}}})
                )
            except (ConnectionClosed, OSError) as exc:
                raise DemoError(
                    "MP2 connection lost while sending a command; its outcome is unknown."
                ) from exc
            self.last_send = time.monotonic()
            return request["MsgId"]

    async def _query(self, command_set, action, predicate):
        async with self.request_lock:
            future = asyncio.get_running_loop().create_future()
            waiter = (predicate, future)
            self.pending.append(waiter)
            try:
                await self._send(command_set, action)
                return await asyncio.wait_for(future, self.config.timeout)
            except asyncio.TimeoutError as exc:
                raise DemoError(
                    "MP2 timed out waiting for {}. Check device mode and subscriptions.".format(
                        action.get(
                            "RegistrationAction", action.get("MenuCategory", "reply")
                        )
                    )
                ) from exc
            finally:
                self.pending.remove(waiter)

    async def get(self, path):
        self.snapshot_paths[path] = self.snapshot_paths.get(path, 0) + 1
        try:
            reply = await self._query(
                "SubscriptionMgr",
                {
                    "RegistrationAction": "GetCresNextObject",
                    "RegistrationActionOptions": {
                        "RcSessionId": self.session,
                        "CresNextObject": path,
                    },
                },
                lambda document: at_path(document, path) is not None,
            )
        finally:
            if self.snapshot_paths[path] > 1:
                self.snapshot_paths[path] -= 1
            else:
                del self.snapshot_paths[path]
        result = at_path(reply, path)
        # Receiver updates are normally pushes. Avoid letting a polled zero
        # reset an already-running timer when this reply contains player data.
        if path.startswith("/Device/MediaPlayerNeXt/Players/") and isinstance(
            result, dict
        ):
            self.players.setdefault(path.rsplit("/", 1)[1], PlayerState()).update(
                result, pushed=False
            )
        return result

    async def fresh_player(self, player):
        """Read the player again; returns its PlayerState."""
        path = "/Device/MediaPlayerNeXt/Players/" + player
        for _ in range(3):
            reply = await self.get(path)
            if reply is None:
                raise DemoError("Unknown player '{}'.".format(player))
            if isinstance(reply, dict) and reply.get("PlayerState"):
                return self.players[player]
            await asyncio.sleep(0.2)  # transient empty snapshot right after an action
        raise DemoError("Player returned only empty snapshots; its state is unknown.")

    async def subscribe(self, *players, favorites=False):
        paths = ["/Device/MediaNavigation/RegisteredClientMenus/" + self.session]
        if favorites:
            paths.append("/Device/MediaFavorites")
        paths += ["/Device/MediaPlayerNeXt/Players/" + player for player in players]

        def acknowledged(document):
            clients = (
                at_path(document, "/Device/SubscriptionMgr/RegisteredClientList") or {}
            )
            subscribed = clients.get(self.session, {}).get("SubscribedTo", {})
            actual = {item.get("CresNextPath") for item in subscribed.values()}
            return set(paths).issubset(actual)

        await self._query(
            "SubscriptionMgr",
            {
                "RegistrationAction": "SubscribeToObject",
                "RegistrationActionOptions": {
                    "RcSessionId": self.session,
                    "CresNextPath": paths,
                },
            },
            acknowledged,
        )

    async def browse(self, profile, provider, item=None, offset=0):
        options = {
            "ProviderKey": provider,
            "BrowseKey": provider,
            "ItemCount": 20,
            "ItemOffset": offset,
        }
        if item:
            options["BrowseKey"] = item["BrowseKey"]
            options["SignedData"] = item["SignedData"]
        return await self.navigate(profile, "ProviderBrowseMenu", options)

    async def navigate(self, profile, category, options):
        """One MediaNavigation request (browse, search or home); returns its menu."""
        if self.failure:
            raise self.failure
        label = "Provider browse" if category == "ProviderBrowseMenu" else category
        # Navigation replies echo MsgId. Install the waiter before sending so
        # even an immediate reply cannot be lost.
        # demo_mcp_http/runtime.py sets navigation_lock so a slow provider does not
        # hold up player reads and pause; every other client uses request_lock.
        async with getattr(self, "navigation_lock", self.request_lock):
            future = asyncio.get_running_loop().create_future()
            request_id = str(uuid.uuid1())
            path = "/Device/MediaNavigation/RegisteredClientMenus/" + self.session

            def matched(document):
                node = at_path(document, path) or {}
                # A refusal can arrive as a bare Notification without the MsgId echo
                # (seen on firmware 0.6855: CERT_HAS_EXPIRED). Requests are serialized
                # per session, so a Notification echoing no other MsgId answers this one.
                echoed = node.get("LastRequestAction", {}).get("MsgId")
                return echoed == request_id or (
                    bool(node.get("Notification")) and echoed is None
                )

            waiter = (matched, future)
            self.pending.append(waiter)
            action = {
                "RcSessionId": self.session,
                "MsgId": request_id,
                "ProfileKey": profile,
                "MenuCategory": category,
                "MenuCategoryOptions": options,
            }
            try:
                await self._send("MediaNavigation", action)
                reply = await asyncio.wait_for(future, self.config.timeout)
                node = at_path(reply, path)
                notification = node.get("Notification")
                if notification:
                    raise DemoError(
                        "{} refused: {}".format(label, notice_text(notification))
                    )
                menu = node.get("MenuUpdates", {}).get(category)
                if not isinstance(menu, dict):
                    raise DemoError("{} returned no menu.".format(label))
                return menu
            except asyncio.TimeoutError as exc:
                raise DemoError(
                    "{} timed out; confirm the service is signed in.".format(label)
                ) from exc
            finally:
                self.pending.remove(waiter)

    async def favorites(self, profile):
        """ListFavorites: {FavoriteId: entry}. An empty list never answers, so a
        short timeout is confirmed with a snapshot of the favorites object."""
        path = "/Device/MediaFavorites/Profiles/" + profile

        def listed(document):
            # Our own request echoes on the MediaFavorites root; only a full list
            # (every entry carrying SignedData) under Profiles/<key> answers it.
            entries = (at_path(document, path) or {}).get("Favorites")
            return (
                isinstance(entries, dict)
                and bool(entries)
                and all(
                    isinstance(entry, dict)
                    and isinstance(entry.get("MenuDataItems"), dict)
                    and entry["MenuDataItems"].get("SignedData")
                    for entry in entries.values()
                )
            )

        async with self.request_lock:
            future = asyncio.get_running_loop().create_future()
            waiter = (listed, future)
            self.pending.append(waiter)
            try:
                await self._send(
                    "MediaFavorites",
                    {
                        "RcSessionId": self.session,
                        "ProfileKey": profile,
                        "FavoritesAction": "ListFavorites",
                        "FavoritesActionOptions": {},
                    },
                )
                reply = await asyncio.wait_for(future, min(5, self.config.timeout))
                return at_path(reply, path)["Favorites"]
            except asyncio.TimeoutError:
                pass
            finally:
                self.pending.remove(waiter)
        # An empty list never answers. A profile without favorites may have no node
        # at all (its own path is then an invalid request), so read the whole object;
        # its RequestAction echo carries no other keys and does not count.
        reply = await self._query(
            "SubscriptionMgr",
            {
                "RegistrationAction": "GetCresNextObject",
                "RegistrationActionOptions": {
                    "RcSessionId": self.session,
                    "CresNextObject": "/Device/MediaFavorites",
                },
            },
            lambda document: bool(
                set(at_path(document, "/Device/MediaFavorites") or {}) - {"RequestAction"}
            ),
        )
        profiles = at_path(reply, "/Device/MediaFavorites").get("Profiles") or {}
        if not (profiles.get(profile) or {}).get("Favorites"):
            return {}
        raise DemoError("Favorites list did not arrive; try again.")

    async def load_source(self, player, profile, provider, signed_data):
        """LoadSource with an item's SignedData, unmodified. Returns the baseline."""
        return await self.action(
            player,
            "LoadSource",
            {
                "ProfileKey": profile,
                "ProviderKey": provider,
                "AudioSourceUrl": "",
                "AutoPlay": True,
                "SignedData": signed_data,
            },
        )

    async def action(self, player, action, options=None):
        baseline = self.sequence
        await self._send(
            "MediaPlayerNeXt",
            {
                "RcSessionId": self.session,
                "PlayerId": player,
                "ActionId": action,
                "ActionIdOptions": options or {},
            },
        )
        return baseline

    async def wait_player(self, player, baseline, expected, title=None, timeout=10):
        deadline = time.monotonic() + timeout
        fresh_state = False
        fresh_title = not title
        path = "/Device/MediaPlayerNeXt/Players/" + player
        while time.monotonic() < deadline:
            self.changed.clear()
            if self.failure:
                raise self.failure
            for sequence, document in list(self.history):
                if sequence <= baseline:
                    continue
                delta = at_path(document, path) or {}
                if delta.get("Notification"):
                    raise DemoError(
                        "Player refused the command: {}".format(
                            notice_text(delta["Notification"])
                        )
                    )
                if delta.get("PlayerState") == expected:
                    fresh_state = True
                metadata = delta.get("Player", {}).get("NowPlayingData", {})
                # Confirms our own LoadSource; a push may carry either name field.
                if title and title.casefold() in (
                    text(metadata.get("TrackTitle")).casefold(),
                    text(metadata.get("StationName")).casefold(),
                ):
                    fresh_title = True
            state = self.players.get(player)
            if (
                fresh_state
                and fresh_title
                and state
                and state.data.get("PlayerState") == expected
            ):
                return state.metadata()
            try:
                await asyncio.wait_for(
                    self.changed.wait(), max(0.01, deadline - time.monotonic())
                )
            except asyncio.TimeoutError:
                break
        raise DemoError(
            "Player did not verify '{}' after the command; it may or may not have applied.".format(
                expected
            )
        )

    async def wait_delta(self, player, baseline, test, timeout=10):
        """Wait for a player push after baseline for which test(delta) is true."""
        deadline = time.monotonic() + timeout
        path = "/Device/MediaPlayerNeXt/Players/" + player
        while time.monotonic() < deadline:
            self.changed.clear()
            if self.failure:
                raise self.failure
            confirmed = False
            for sequence, document in list(self.history):
                if sequence <= baseline:
                    continue
                delta = at_path(document, path) or {}
                if delta.get("Notification"):
                    raise DemoError(
                        "Player refused the command: {}".format(
                            notice_text(delta["Notification"])
                        )
                    )
                if delta and test(delta):
                    confirmed = True  # keep scanning: a later refusal still wins
            if confirmed:
                return self.players[player].metadata()
            try:
                await asyncio.wait_for(
                    self.changed.wait(), max(0.01, deadline - time.monotonic())
                )
            except asyncio.TimeoutError:
                break
        raise DemoError(
            "Player did not confirm the command; it may or may not have applied."
        )

    async def close(self):
        if self.socket:
            await self.socket.close()
            self.socket = None
        if self.receiver:
            self.receiver.cancel()
            await asyncio.gather(self.receiver, return_exceptions=True)
            self.receiver = None
