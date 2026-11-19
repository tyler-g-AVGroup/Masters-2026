# Client essentials

The parts of a Media Player 2.0 client that are easy to get wrong. The device
behaviors described here were observed on the devices tagged [A] or [B] in
`api-gotchas.md`; the handling
advice follows from them. Steps are given in plain terms; implement them in the project's language.

## 1. Connect and log in

`wss://<device_ip>/subscriptionmgr` with an `Authorization` header built as
the Make-API-Calls topic describes:

1. `nonce` = a random UUID (string); `ts` = the current Unix time in whole seconds (string).
2. `sig` = base64( HMAC-SHA256( key = base64-decode(`client_secret`),
   message = UTF-8 bytes of `client_id` + `"GET"` + `uri` + `ts` + `nonce` ) ).
3. `info` = base64( UTF-8 bytes of `client_id` + `":"` + `sig` + `":"` + `nonce` + `":"` + `ts` ).
4. Header: `Authorization: CrestronAuth-SHA256 <info>` (one space after the scheme).

Every request's `MsgId` is a UUIDv1, as the docs ask (it embeds this host's MAC address).

`client_id` and the base64 `secret` come from `createclient <name>` on the
device console. `uri` is the full `wss://.../subscriptionmgr` URL. The
signature includes a timestamp, so keep the client's clock synced. A wrong
secret is rejected during the WebSocket upgrade (see "Login" in
`api-gotchas.md`): report it as a login problem, not a network one.

**TLS.** The device usually uses a self-signed certificate. Connect over TLS without
checking it (`verify_tls: false` in the config): turn off both hostname and
certificate-chain checks in the WebSocket library's TLS options; the
connection is still encrypted and no certificate file is needed. If the device
has a trusted certificate, keep the checks on.

## 2. Session setup, in this order

1. `RegisterClient` with a label unique to this run (e.g. `myapp-<uuid>`); the
   reply's `WsConnectionsList.*.RegisteredClientList` key whose
   `RegisteredClientId` equals your label is your `RcSessionId`.
2. `GetCresNextObject /Device/MediaPlayerNeXt/Players` to list players (hide
   `ready` placeholders; see the gotchas).
3. One `SubscribeToObject` for
   `/Device/MediaNavigation/RegisteredClientMenus/<RcSessionId>`,
   `/Device/MediaFavorites` and each player path. Without the menu-node
   subscription, browse/search/home replies never arrive. Treat a missing
   acknowledgment as a startup failure.
4. Optionally `GetCresNextObject /Device/StreamingServices/UserProfiles` to
   discover the signed-in profile/provider pairs instead of configuring them.

Envelope: `{"Device": {"<CommandSet>": {"RequestAction": {...}}}}` with a
`MsgId`. `RcSessionId` goes in `RegistrationActionOptions` for
`SubscriptionMgr`, and directly in `RequestAction` for `MediaPlayerNeXt`,
`MediaNavigation` and `MediaFavorites`.

## 3. Receive loop and reply matching

- Keep one long-lived connection and one receive loop. Every frame can hold
  several JSON documents: parse it as described under "One WebSocket frame" in
  `api-gotchas.md`. Hand each document to the request waiting for it, and
  treat the rest as pushes.
- **Navigation** (`MediaNavigation`): replies carry
  `LastRequestAction.MsgId` equal to your request's `MsgId`; match on it. The
  reply is at `RegisteredClientMenus.<RcSessionId>.MenuUpdates.<MenuCategory>`.
  A `Notification` there (with a `NotiId` you haven't seen) is a prompt to
  show and answer. Serialize navigation requests per session.
- **Player actions** (`MediaPlayerNeXt`): fire and forget; the result arrives
  as pushes on the player path. A `Notification` on the player path means the
  action was refused (show it, then answer with `ActionId: "Notification"`).
- **Favorites** (`MediaFavorites`): replies are matched by path
  (`/Device/MediaFavorites/Profiles/<ProfileKey>`). Only a reply whose every
  entry has `MenuDataItems.SignedData` is a full `ListFavorites` result; other
  replies are deltas (`{}` = deleted). An empty list never replies: time out
  after a few seconds and confirm with `GetCresNextObject` (`{"Favorites": {}}`).
- **Snapshots** (`GetCresNextObject`): matched by path. Merge them onto known
  state rather than replacing it.
- On connection loss, fail every pending request at once, tell the user, and
  reconnect with backoff (log in, register, resubscribe, re-read state).

Working values on [B] (values that worked, not device limits): 10 s to open the
WebSocket, 12 s for a navigation or snapshot reply, 5 s for `ListFavorites` (then the snapshot
check), up to 15 s for a `LoadSource` to report `playing`, 10 s for other player actions, at
least 10 s between new connections, about 100 ms between requests.

Players: read `/Device/MediaPlayerNeXt/Players` instead of assuming a count. [B] listed more slots
than it has players; slots not in use report `PlayerState: "ready"` and should be hidden.

## Configuration file

One `config.json` beside the app (gitignored, readable by its owner only), shared by Media Player 2.0 and REST
clients:

| Key | Needed for | Notes |
|---|---|---|
| `device_ip` | both | |
| `client_id`, `client_secret` | Media Player 2.0 | from `createclient`; secret is base64 |
| `profile` | Media Player 2.0 | default `Profile1` (a generic slot name, not a sample identifier) |
| `provider` | Media Player 2.0 | optional; else find TIDAL under the profile's `AssignedProviders` |
| `player` | single-player apps | default `Player01` (generic slot name) |
| `admin_user`, `admin_password` | REST | the device's web UI admin login |
| `credentials_file` | optional | read the client id and secret from another JSON |
| `verify_tls` | both | `false`: TLS without checking the device's self-signed certificate |

Treat `<...>` placeholder values as missing.

## 4. State the UI shows

- Merge every player push into the known player object, whatever it
  contains; pushes are partial (a shuffle change is only
  `{"Player": {"Shuffle": true}}`). Replace lists (e.g. `AvailableActions`)
  instead of merging into them, except the transient `AvailableActions: {}`
  push: keep the last list then (see api-gotchas.md), or every control
  flickers off.
- Ignore a `GetCresNextObject` snapshot of the player that has neither
  `PlayerState` nor `NowPlayingData`: it is the transient empty reply right
  after an action.
- Title = trimmed `Player.NowPlayingData.TrackTitle`, else trimmed
  `StationName`. Trim every text field (blank fields are `" "`).
- Enable each transport control only when `AvailableActions` lists it. Exception: `Shuffle` and
  `Repeat` worked on [B] while stopped, when only `Play` was listed.
- Position: estimate from the last pushed `ElapsedSec` plus elapsed time while
  `playing`; hide total time and scrubber when `Duration` is 0 or less (0 = live radio,
  -1 = still loading).
- Artwork (`AlbumArtUrl`, `UrlIcon`) comes from the provider: accept only plain
  `http(s)` URLs and assign them (and all provider text) as values through the
  UI toolkit, never by concatenating them into markup; otherwise show a
  placeholder.

## 5. Browsing and playing

- Root menu: `ProviderBrowseMenu` with `BrowseKey` = the provider key and no
  `SignedData`. Open a folder with the item's own `BrowseKey` and `SignedData`.
- Next page (folders and search results alike): `ProviderBrowseMenu` on the
  last response's `ParentBrowseKey` (its `BrowseKey` and `SignedData`,
  unmodified) with `ItemOffset` advanced by `Page.limit`.
- Play: `LoadSource` with the item's `SignedData` unmodified, for `song`,
  `station` and `podcastepisode` items only. Playlists, albums and folders are
  opened, and a track inside them is played.
- Skip `null` entries in any `MenuDataItems` list.
