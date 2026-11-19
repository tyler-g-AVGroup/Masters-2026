# Differences between the public docs and real MP2 behavior

Each entry is tagged with the device it was observed on:

- **[A]** an earlier DM-NAX test unit with TIDAL. Treat [A]-only entries as provisional.
- **[B]** the main DM-NAX test unit, with TIDAL and Internet Radio signed in.

Other products, firmware or providers may differ: re-confirm before relying
on an entry, and record the product, firmware and provider whenever you
confirm or refute one. Read the firmware with `GetCresNextObject /Device/DeviceInfo`
(`DeviceVersion`), the console command `ver`, or the web UI. Entries under
"Unconfirmed" are hypotheses, not findings.

## Response shapes

- **`NowPlayingData` is nested one level deeper than the player object.** [A, B]
  The real path is `Device.MediaPlayerNeXt.Players.<PlayerId>.Player.NowPlayingData`,
  not `...Players.<PlayerId>.NowPlayingData`. `PlayerState` and
  `AvailableActions` are direct children of the player object; `NowPlayingData`
  and its siblings `ProviderKey`, `ProfileKey`, `SignedData`, `Shuffle` and
  `Repeat` live under the nested `Player` key. Seen in both `GetCresNextObject`
  replies and pushes.
- **Pushes are partial deltas, not snapshots.** [A, B] One push's
  `NowPlayingData` was exactly `{"ElapsedSec": 80}`, with no title and no
  `PlayerState`; a shuffle change pushes only `{"Player": {"Shuffle": true}}`.
  Merge each push onto the known state instead of replacing it.
  `GetCresNextObject` normally returns the complete object (see the transient
  empty reply below). A transient push of `{"AvailableActions": {}}` (an empty
  object, not a list) also occurs; never iterate it as a list. On [B] it came
  with almost every Play, Pause, LoadSource and track change; keep the last
  list instead of reading it as "nothing enabled", or every control flickers off.
- **Blank text fields are a single space `" "`, not empty.** [B] A stopped
  player reports `TrackTitle`, `StationName`, `ArtistName`, `AlbumName` and
  `AlbumArtUrl` as `" "`. A space counts as non-empty, so "use `TrackTitle`
  if set, else `StationName`" picks the space and the UI shows a blank title
  or a stray separator. Trim every text field before testing it.
- **`TrackTitle` is usually blank for TIDAL tracks; the title is in
  `StationName`**, even when `StreamingMediaType` is `"song"`. [A, B] Seen on
  playlist tracks, search hits and favorites. Use the trimmed `TrackTitle`,
  else the trimmed `StationName`; `StationName` does not mean radio.
- **`SearchMenu` results include full `SignedData`**, although the Search API
  field list omits it. [A, B] A search hit can be played directly with
  `LoadSource`.
- **Search categories are lowercase: `song`, `album`, `artist`, `playlist`.**
  [A, B] `Song` (seen on both), `track` and `podcast` (seen on [A]) raise a
  device Notification "Invalid Search Category provided in request" with an
  `OK` input; show it to the user and then answer it. On [A], `all` and
  `station` returned a `Categories` entry whose value is `null`; guard for it.
  Only `song` results are directly playable; `album`, `artist` and `playlist`
  results are folders (artist hits are `dirmenu` and open to e.g. "Artist
  Radio", "Discography", "Albums"). One category per request, so a combined
  view needs one `SearchMenu` request per category.
- **Searching all providers at once returned nothing.** [B]
  `SearchProviderKey` `"ALL"` (the doc example), `"All"` and `"all"`, with `ItemCount: 1`, all returned
  `TotalItemCount: 0` and `MenuDataItems: [null]` for a query with many TIDAL
  hits. Search each provider separately, and skip `null` items.
- **`LoadSource` on a playlist item fails.** [B] Both playlists tried (a
  personal TIDAL mix and an editorial playlist) raised the player Notification
  "Set Station Failed:This track is not currently available." and stayed
  `stopped`. Open the playlist as a folder and `LoadSource` a `song` inside it:
  the device then queues the rest of the playlist, and
  `NextTrack`/`PreviousTrack` move through it. Albums were not tried; open them
  the same way. Treat only `song`, `station` and `podcastepisode` as directly
  playable.
- **The player briefly reads as empty right after Play, Pause, LoadSource or
  ThumbsUp.** [A, B] `GetCresNextObject` on the player then has no
  `PlayerState` and no `NowPlayingData` for a moment. Treat a reply with
  neither as transient and keep the last good state; otherwise the UI flashes
  "Not playing" and resets any estimated position.
- **`AvailableActions` decides which transport controls apply.** [A, B]
  While a TIDAL track played the list was `Pause, Shuffle, Repeat, Loop,
  NextTrack, Seek, Ffwd, Rewind` (`Play` instead of `Pause` when paused).
  `PreviousTrack` was absent for the first track and appeared once
  `NextTrack` had moved into a queue. A stopped player that has played before
  lists only `Play`; a player that has never played has no `AvailableActions`
  key at all, so treat a missing list as "nothing
  enabled". `NextTrack`/`PreviousTrack` sent while stopped raise "Requested
  action not supported for this service". Enable every transport control from
  this list. During a skip on [B] the player reported `stopped` and briefly
  dropped `NextTrack` before the new track reached `playing`.
- **Live radio reports metadata differently.** [B] An Internet Radio
  station had `TrackTitle` = the current song as
  `"<song> / <artist>"`, `StationName` = the station name, `ArtistName` = `" "`,
  `Duration` 0, and `AvailableActions` = `["Pause"]` only. Show the station as
  the subtitle, and show no total time or scrubber when `Duration` is 0.
- **`Duration` is `-1` while a track loads.** [B] After `LoadSource` and on
  each track change, `NowPlayingData.Duration` was `-1` for a moment, then the
  real length. Treat `Duration <= 0` as unknown: no scrubber, no total time,
  and don't clamp the position estimate to it.
- **`Stop` did nothing.** [B] It was not listed in `AvailableActions` for any
  track or station tried, and sent while playing it was silently ignored (no
  state change, no Notification). Use `Pause`.
- **Thumbs: `RatingOptions` exists even when the provider rejects rating.**
  [B] TIDAL reported `RatingOptions: {"ThumbsUp": false, "ThumbsDown": false}`
  on every track tried, did not list `ThumbsUp`/`ThumbsDown` in
  `AvailableActions`, and answered `ThumbsUp` with the Notification "Feedback
  currently not supported for this service". Show rating controls only when
  `AvailableActions` lists them.
- **Position: polled `ElapsedSec` is 0; pushes report it after jumps.** [A, B]
  On [B], `GetCresNextObject` returned `ElapsedSec: 0` throughout a playing
  track. Pushes carried the new `ElapsedSec` right after `Seek`
  (`{"Position": 120}` pushed 120), `Ffwd`/`Rewind` (about ±15 s) and a track
  change (0), and none during 10 s of normal playback. Estimate position from
  the last pushed value plus elapsed time while `playing`, re-anchor on every
  pushed `ElapsedSec`, and clamp to `Duration`. `Seek` works on [B], so a
  scrubber is fine when `AvailableActions` lists `Seek`.
- **One WebSocket frame can contain several JSON documents joined by
  newlines.** [A] Seen when two requests were sent back to back: the device
  coalesced an acknowledgment and a later push into one frame, and parsing the
  frame as a single JSON document failed with an "extra data" error. Parse
  every frame as a sequence: skip whitespace, decode one JSON document and
  note where it ended, repeat from there until the frame is used up. Where the
  standard parser cannot report the end offset of one document, use a
  streaming JSON parser or split on document boundaries; never assume one
  document per message.
- **`/Device/MediaPlayerNeXt/Players` lists placeholder players.** [B] The
  test unit listed more `PlayerNN` slots than it has players. Real players
  reported `stopped` or a playing state; the extra slots reported `ready` with
  an empty `AvailableActions` and no `NowPlayingData`. Hide `ready` slots (check
  the count against the model's datasheet if unsure); do not hide a real
  player just because it has never played.
- **Signed-in services are readable.** [B] `GetCresNextObject /Device/StreamingServices/UserProfiles`
  returns each `ProfileN` with its `AssignedProviders` (`ProviderN` with a
  provider name), so profile/provider pairs can be discovered instead of
  configured by hand.
- **Navigation replies echo the request's `MsgId`.** [B] Browse, home and
  search replies carry `LastRequestAction.MsgId` equal to the request's
  `MsgId`, so they can be matched exactly. Player and favorites replies had
  no such echo; match them by path and content.

## Pagination [B]

On [A] neither method below advanced; on [B] the first one works for folders
and search results:

- **Next page = `ProviderBrowseMenu` on the previous response's
  `ParentBrowseKey`**, sending its `BrowseKey` and its `SignedData` unmodified,
  with `ItemOffset` advanced by the page size. A large folder and a multi-page
  search both paged cleanly, with no overlap. Search results
  page this way too: the search response's `ParentBrowseKey` is a browsable
  `playlist` node.
- **What did not work:** re-sending the clicked item's own `SignedData` with a
  larger `ItemOffset` (page 1 again), and re-issuing `SearchMenu` with
  `ItemOffset` (ignored; page 1 again).
- The page size is `ParentBrowseKey.SignedData.SourceData.Page.limit` (20);
  an `ItemCount` below it was ignored. The Pagination API describes a
  non-empty `Page.PageUrl` as cursor paging, yet on [B] `PageUrl` was
  non-empty (`...?p=%value%`) and offset paging worked.
- A provider's root menu ignores `ItemCount`/`ItemOffset` and returns every
  entry.
- Dedupe appended rows by `BrowseKey` and hide "Load more" when a page adds
  nothing, in case other firmware behaves like [A].

## Favorites [B]

- **`AddFavorite` replies with a name prompt**: a Notification with
  `UserInputReq: "Alphanumeric"`, `InitialUserInput` (the item's name) and
  inputs `OK`/`Cancel`. It arrives at
  `/Device/MediaFavorites/Profiles/<ProfileKey>/Notification` (as the
  Notification topic says), but its `Msg` is "Enter in your Favorite's name",
  not the doc's "Enter a name for this favorite"; don't match on the text.
  Answer with `FavoritesAction: "Notification"`,
  `UserInputSelected: "OK"` and the name in `UserInputText`. Adding works from
  the player's `SignedData` (`.../Players/<id>/Player/SignedData`) and from a
  browsed or searched item's `SignedData`.
- **Replies to Add, Rename, Move and Delete are deltas**: Add pushes the new
  favorite without `SignedData`, Rename pushes only the new name, Move pushes
  only changed `OrderNumber`s, and Delete maps each deleted id to `{}` and
  renumbers the rest. Treat `{}` as "remove". After answering the Add prompt,
  the clearing `{"Notification": {}}` can arrive before the new favorite.
- **Only `ListFavorites` includes `SignedData`**, on every entry.
  `GetCresNextObject` on `/Device/MediaFavorites/Profiles/<ProfileKey>`
  returns the list without it, so it cannot be used to play a favorite.
  Playing a favorite with the `ListFavorites` `SignedData` via `LoadSource`
  works. A reply whose entries lack `SignedData` is a delta, not the list.
- **`ListFavorites` on an empty list never answers.** Use a short timeout and
  confirm emptiness with `GetCresNextObject` (it returns `{"Favorites": {}}`).
- **An empty `{"Notification": {}}` push clears a prompt.** It arrives after
  a prompt is answered; do not show it as a dialog.
- **Your own requests are echoed back.** While subscribed to
  `/Device/MediaFavorites`, every `MediaFavorites` request this session sent
  came back as a push of `{"Device": {"MediaFavorites": {"RequestAction": ...}}}`.
  Match replies under `Profiles/<ProfileKey>`, never on the `MediaFavorites`
  root, or the echo resolves the wait.

## Timing and concurrency

- **Navigation replies only arrive after subscribing to the session's menu
  node.** [B] Without a subscription to
  `/Device/MediaNavigation/RegisteredClientMenus/<RcSessionId>`, a
  `MediaNavigation` request is acknowledged and its result never arrives
  (12 s timeout without it, an immediate reply right after subscribing on the
  same session). Subscribe to it right after registering, together with the
  player paths.
- **Requests that wait for a resulting `PlayerState` need a subscription on
  that player's path.** [A] The new state only arrives as a push; without a
  subscription to `/Device/MediaPlayerNeXt/Players/<PlayerId>` the wait times
  out. Subscribe right after discovering the players, before any player
  action.
- **Use one receive loop per connection** that hands each message to the
  request waiting for it and forwards the rest as pushes (see
  `client-essentials.md`). [A] A separate "listen for pushes" reader
  and a request/response caller sharing one lock blocked each other.
- **The API became unreachable during connection-stress testing; root cause
  unknown.** [B] After an hour of many short-lived test sessions, the device
  refused every WebSocket handshake (ping and web UI still answered) until a
  power cycle. Keep one long-lived connection per app, close it cleanly on
  exit, back off on failure, and when testing watch
  `ConnectedClientWsCount` in `GetCresNextObject /Device/SubscriptionMgr` (the
  docs cap connections at 30). The same object reports
  `ExpirationDurInSecs: 1200` (20-minute session expiry).
- **Reconnecting right after a connection closed can fail.** [A] A new
  connection registered and then died on its first request with
  WebSocket close code 1002 (protocol error); a retry, once after
  15 s, succeeded. Not seen on [B] across about a dozen back-to-back
  connections. Retry with a short backoff.

## Unconfirmed

- Two requests sent within about 1 ms of each other were sometimes dropped on
  [B], so a startup menu load timed out; spacing requests about 100 ms apart
  fixed it (seen once). Spacing or serializing requests per session may avoid it; unconfirmed.
- [B] advertises a 20-minute session expiry, yet an idle session still
  answered after 21.5 minutes, and again after about 22 minutes (seen twice,
  never a refusal). A long-running client should
  still re-register when a request fails with `INVALID_RC_SESSION_ID`. Where that error appears in
  the reply is not documented or captured; a working approach is to match the string anywhere in a message.
- `GetCresNextObject` replies are matched by path only; while subscribed to
  the same path, a push could in principle satisfy the match. Never observed.
- An unanswered player Notification may be delivered again to a later
  session (seen once on [B]). Answer every Notification you show.

## Architecture

- **Login.** A wrong client secret is rejected during the WebSocket upgrade:
  on [B] the device answered with HTTP status 200 instead of 101, which most
  WebSocket libraries report as a rejected handshake, not an authentication
  error. Map it to "check client_id and secret" in your error message.

- **Browser-direct login.** The docs (May 2025 update) allow the credentials
  in the `Sec-WebSocket-Protocol` header as `CrestronAuth-SHA256.<credentials>`
  (dot, not space), since a page cannot set `Authorization`. [B] accepted the
  handshake (tested from a non-browser client, not a real browser). The page then holds the
  client secret and every browser must trust the device's self-signed
  certificate, so route pages through a bridge that holds the connection.
- **The navigation node (`RegisteredClientMenus`) belongs to the registered
  session, not to a browser tab.** If one bridge serves several tabs, keep no
  per-tab navigation state on the server: have each command carry its full
  context (profile key, provider key, and a browse key with its signed data or
  a returned pagination cursor), keep breadcrumbs in the browser, and
  serialize navigation requests per session (the node has a single
  `LastRequestAction`).
