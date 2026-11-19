# Media Player 2.0 feature matrix

What a client can do, the request that does it, and how far each item has
been verified. Doc revision: Sept 2, 2026 (What's New). Hardware column:
the main test unit ([B] in `api-gotchas.md`) with TIDAL, unless noted; blank = not tried. Quirks behind each "yes" are in `api-gotchas.md`.
Request bodies are in the official topics listed in SKILL.md; connection and
reply-matching details are in `client-essentials.md`.

Every request is `{"Device": {"<CommandSet>": {"RequestAction": {...}}}}` with
a `MsgId` (UUIDv1). Command sets: `SubscriptionMgr`, `MediaPlayerNeXt`,
`MediaNavigation`, `MediaFavorites`. After registration, `RcSessionId` goes
inside `RegistrationActionOptions` for `SubscriptionMgr` requests, and
directly inside `RequestAction` for the other three.

## Connection and session (SubscriptionMgr)

| Feature | Request | Docs | Hardware |
|---|---|---|---|
| Connect | `wss://<ip>/subscriptionmgr`, header `Authorization: CrestronAuth-SHA256 <b64(id:sig:nonce:ts)>`, HMAC-SHA256 over `id+"GET"+uri+ts+nonce` with the base64-decoded secret | yes | yes |
| Connect from a browser | same credentials in `Sec-WebSocket-Protocol: CrestronAuth-SHA256.<credentials>` | yes (May 2025) | handshake accepted (tested from a non-browser client, not a real browser); still needs the device cert trusted and exposes the secret to the page |
| Create credentials | console `createclient <name>` (also `addclient`, `listclients`, `deleteclient`) | yes | yes |
| Register | `RegistrationAction: RegisterClient`, `RegisteringClientIds: [<your id>]` → `RcSessionId` is the key under `WsConnectionsList.*.RegisteredClientList` | yes | yes |
| Subscribe to pushes | `SubscribeToObject`, `CresNextPath: [menus node, /Device/MediaFavorites, /Device/MediaPlayerNeXt/Players/PlayerNN...]` | yes | yes (needed before state-confirming actions) |
| Unsubscribe | `UnsubscribeFromObject` | yes | yes: acknowledged, and no further pushes for that path |
| Read any object | `GetCresNextObject`, `CresNextObject: <path>` | yes | yes |
| Limits | 30 WebSocket connections, 30 sessions each; the player count differs by model | yes | the test unit lists more `PlayerNN` slots than it has players; the extra slots report `ready` with no actions |
| Discover players | `GetCresNextObject /Device/MediaPlayerNeXt/Players` and read the keys | implied | yes |
| Discover profile/provider pairs | docs point at `/Device/MediaNavigation/SearchProviderKeyAccessors` and `BrowseKeyAccessors` but never show their shape | partial | yes: `GetCresNextObject /Device/StreamingServices/UserProfiles` lists each profile's `AssignedProviders` with names |

## Playback (MediaPlayerNeXt, `PlayerId` + `ActionId`)

| Feature | ActionId / options | Docs | Hardware |
|---|---|---|---|
| Play an item | `LoadSource {ProfileKey, ProviderKey, AudioSourceUrl:"", AutoPlay, SignedData}`; SignedData from a browse/search/favorite item, unmodified | yes | yes for `song` items from browse, search, home and favorites; **`playlist` items failed** ("not currently available"): open them and play a track inside |
| Play a URL (generic provider) | `LoadSource` with `AudioSourceUrl` | mentioned only | |
| Internet radio station | `LoadSource` with a `station` item's `SignedData` (Internet Radio provider) | yes | yes: `TrackTitle` = "song / artist", `StationName` = station, `Duration` 0, only `Pause` in `AvailableActions` |
| Play / Pause | `Play {}`, `Pause {}` → `PlayerState` playing/paused | yes | yes |
| Next / Previous | `NextTrack {}`, `PreviousTrack {}`; not for live stations | yes | yes; enable from `AvailableActions` (`PreviousTrack` appears only after moving into a queue; sent while stopped both raise a Notification) |
| Seek | `Seek {Position: seconds}` → `ElapsedSec` push | yes | yes: pushes the new `ElapsedSec` immediately |
| Skip ±15 s | `Ffwd {}`, `Rewind {}` | yes | yes |
| Shuffle | `Shuffle {ShufState: bool}` → `Player.Shuffle` | yes | yes (works even while stopped) |
| Repeat | `Repeat {RepState: 0 off, 1 track, 2 list}` → `Player.Repeat` | yes | yes |
| Rate | `ThumbsUp {}`, `ThumbsDown {}` → `Player.RatingOptions`; provider-dependent | yes | no on TIDAL: not in `AvailableActions` for any track tried; sending it raised "Feedback currently not supported for this service" |
| Stop | listed in `AvailableActions` samples, no topic of its own | partial | **no**: not in `AvailableActions` in any case tried; sent while playing it was silently ignored; use `Pause` |
| Which buttons to enable | read `AvailableActions` on the player object; it changes with content and state | yes | yes |
| Now-playing metadata | `Player.NowPlayingData`: `TrackTitle`, `StationName`, `ArtistName`, `AlbumName`, `AlbumArtUrl`, `Duration`, `ElapsedSec`, `Seekable`, `StreamingMediaType`, `RatingOptions` | yes | yes; blank fields are `" "` (trim them); `TrackTitle` usually blank with the title in `StationName`; polled `ElapsedSec` was 0; pushed after seek, skip and track change |
| Reconnect recovery | `GetCresNextObject` on the player to re-read full state | yes | yes |
| Unsupported action | device pushes `Players.<id>.Notification`; answer with `ActionId: Notification {NotiId, UserInputSelected, UserInputText}` | yes | yes ("Requested action not supported for this service" for `NextTrack` while stopped) |

## Navigation (MediaNavigation, `ProfileKey` + `MenuCategory`)

| Feature | MenuCategory / options | Docs | Hardware |
|---|---|---|---|
| Provider root menu | `ProviderBrowseMenu {ProviderKey, BrowseKey: <ProviderKey>, ItemCount, ItemOffset}` | yes | yes |
| Open a folder | same with the item's `BrowseKey` and its `SignedData` | yes | yes |
| Home screen | `HomeScreenMenu {HomeScreenCategory: "All" or e.g. "PlayHistoryMenu", ItemCount, ItemOffset: 0 for All}`; categories such as Frequently Played, Play History appear only after something has played | yes | yes ("Frequently Played", "Play History" etc. with playable `SignedData`) |
| Search | `SearchMenu {SearchProviderKey, SearchText, SearchCategory, ItemCount, ItemOffset}`; one category per request; categories `song`, `album`, `artist`, `playlist`, `station`, `podcastseries` | yes | yes for the first four, lowercase only; invalid values raise a navigation Notification |
| Multi-provider search | `SearchProviderKey: "ALL"` (doc example) with `ItemCount: 1` per provider rule | yes | **no**: `"ALL"`, `"All"` and `"all"` returned 0 results with `MenuDataItems: [null]`; search per provider |
| Song search hits playable directly | hits carry `SignedData`; `song` hits play with `LoadSource`, `album`/`artist`/`playlist` hits are folders | not shown in field list | yes |
| Pagination | advance `ItemOffset` by page size; resend the `ParentBrowseKey.SignedData` unmodified; honour `Page.limit`; the doc says a non-empty `Page.PageUrl` means cursor paging | yes (V2) | **yes, one way only**: `ProviderBrowseMenu` on the response's `ParentBrowseKey` (its `BrowseKey` + `SignedData`) with the next `ItemOffset`, for folders and search alike; `SearchMenu` ignores `ItemOffset`; an item's own `SignedData` returns page 1; root menus ignore paging; offset paging worked although `PageUrl` was non-empty (did not advance on device [A], see the gotchas) |
| Response location | `RegisteredClientMenus.<RcSessionId>.MenuUpdates.<MenuCategory>.Categories.ItemNN.MenuDataItems`, plus `ParentBrowseKey`; `LastRequestAction.MsgId` echoes the request | yes | yes (match replies on the echoed `MsgId`) |
| Item fields | `BrowseItemName`, `BrowseKey`, `UrlIcon`, `StreamingMediaType` (`dirmenu`, `song`, `album`, `artist`, `playlist`, `station`, `podcastseries`, `podcastepisode`), `MediaTypeMetaData {ProviderKey, ArtistName, AlbumName}`, `SignedData` | yes | yes |
| Navigation prompt | `RegisteredClientMenus.<sid>.Notification`; answer on MediaNavigation with `ActionId: Notification` | yes | yes (invalid search category), answered with `ActionId: Notification` |

## Favorites (MediaFavorites, `ProfileKey` + `FavoritesAction`)

| Feature | FavoritesAction / options | Docs | Hardware |
|---|---|---|---|
| Add current track | read `/Device/MediaPlayerNeXt/Players/<id>/Player/SignedData`, then `AddFavorite {BrowseItemName, StreamingMediaType, ArtistName, AlbumName, ProviderSave, SignedData}`; device replies with a name prompt (`UserInputReq: Alphanumeric`, `InitialUserInput`) that must be answered with `FavoritesAction: Notification` | yes | yes; answer the prompt with `UserInputSelected: "OK"` |
| Add a browsed item | same call with the item's `SignedData` | not stated | yes |
| List | `ListFavorites {}` → `Profiles.<ProfileKey>.Favorites.<FavoriteId> {OrderNumber, CreatedTime, MenuDataItems}` | yes | yes; the only read that includes `SignedData`; **no reply at all when the list is empty** (time out short, confirm with `GetCresNextObject`) |
| Play a favorite | `LoadSource` with the favorite's `MenuDataItems.SignedData` | implied (SignedData present) | yes, with the `ListFavorites` `SignedData` |
| Rename | `RenameFavorite {FavoriteId, NewFriendlyName}` | yes | yes (reply is a delta with only the new name) |
| Delete | `DeleteFavorites {FavoriteIds: [...]}`; others renumber | yes | yes (reply maps each deleted id to `{}`; the rest renumber) |
| Reorder | `FavoriteMovePosition {FavoriteId, Position}` | yes | yes (reply carries only `OrderNumber` deltas) |
| Save to provider too | `ProviderSave: true` | yes | not tried: it writes to the user's streaming account |

## Not in the API

Volume, zone routing, EQ, input selection, device settings. Those live in the
separate DM-NAX REST API (skill `crestron-nax-rest`), not Media Player 2.0; a
full music UI usually needs both.
