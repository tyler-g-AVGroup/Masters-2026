# UI pattern: light list

A light, table-based music layout built from common streaming-app
conventions. Use the installed system font through CSS
(`system-ui, sans-serif`), generic inline SVG icons, and the dealer's brand
color as the single accent (default `#3a6df0`). Ship no logos, icons, fonts or
signature colors from other products, and never name the app after another
brand. The theme is always light.

## Layout regions

- **Sidebar** (220 px, fixed): app name; **player picker** (which `PlayerNN`
  this UI controls: list the `Players` keys, hide `ready` placeholders,
  default to the configured or first player, show each one's `PlayerState`);
  service picker (profile/provider pairs); primary nav (Home, Search, Browse,
  Favorites); then a divider, the service name as a small caps label, and the
  provider's own root categories from the `ProviderBrowseMenu` root response.
  No invented nav items.
- **Page header**: page title 28 px bold; on the Search page a search field
  (40 px high) with category pills (32 px high) beneath it.
- **Folder page (album/playlist)**: hero block with 200 px square artwork
  (`UrlIcon`), kind label (12 px caps), title 32 px bold, artist line and
  total item count (from `TotalItemCount`), and a "Play" button that plays the
  first playable item.
- **Track table**: header row (12 px caps, secondary color), then rows 48 px
  high with 36 px artwork and columns Song | Artist | Album (40 / 30 / 30 %),
  plus an actions column on the right when rows have actions. Folders inside
  a folder render as a card grid (160 px cards, 16 px gutter) above the table.
- **Home**: one section per `HomeScreenMenu` category, heading 20 px bold;
  folder items (albums, playlists, mixes) as a horizontally scrolling row of
  160 px square cards, playable items (songs, stations) as table rows.
  Sections are empty until something has played; say so.
- **Player** (floating panel, max 820 px wide, centered 14 px above the bottom
  edge, 12 px radius, soft shadow): transport on the left (shuffle, previous,
  play/pause, next, repeat), 40 px artwork with title (14 px bold) and
  artist/album or station (12 px) in the middle, a 4 px progress line with
  elapsed and total times beneath, extras (thumbs, favorite) on the right.
- **Now Playing screen** (full screen, opened from the player's artwork or
  title, closed with a chevron or Esc): artwork up to 400 px over a blurred
  copy of it, title 28 px bold, artist, album, progress with times, the full
  transport (play/pause 64 px), thumbs and favorite, then one details line
  with the media type, the service name and any non-blank `Codec`/`BitRate`
  (present on the tested device but usually blank). The API has no queue
  read, so there is no queue view.
- **Device prompt dialog** (modal, 360 px): shows any `Notification` from the
  player, navigation or favorites nodes: its message, a text field when
  `UserInputReq` is `Alphanumeric` (prefilled with `InitialUserInput`), and one
  button per `UserInputs` entry. Answer with the chosen input; close it when a
  `{"Notification": {}}` push arrives.
- **Artwork fallback**: when artwork is absent or not a plain http(s) URL,
  show a gradient tile with the item's initials.

## Sizes and states

- Colors: background `#ffffff`, panels `#f6f6f8`, hover `#ececf0`, text
  `#1b1c22`, secondary text `#6a6f7a`, lines `#e2e2e6`, accent = dealer color.
- Type: titles 28-32 px bold, section headings 20 px bold, body 14 px, captions
  12 px.
- Touch targets at least 44 px for touch panels; icon buttons 36 px (transport
  44 px, Now Playing play/pause 64 px).
- Hover: row and button background `#ececf0`. Focus: 2 px accent outline.
  Disabled (action not in `AvailableActions`; `Shuffle` and `Repeat` stay enabled): 35 % opacity, no pointer.
  Active toggles (shuffle, repeat on): accent color.
- Loading: keep the old list visible with a thin accent bar at the top; empty:
  one centered sentence ("Nothing here", "No favorites yet"); error: an inline
  banner with the device's message or a timeout notice.
- Progress: click to seek when `Seek` is listed; no drag needed. Hide total
  time and progress line when `Duration` is 0 or less (live radio, or -1 while loading).
- Below 760 px wide: the sidebar becomes a top bar with the pickers and a
  4-item nav; the table drops the Album column; the player spans the width.

## State fields shown

From `Player.NowPlayingData` (nested path in `../api-gotchas.md`): title
(trimmed `TrackTitle`, else trimmed `StationName`), artist, album, artwork,
`Duration`. From the player object: `PlayerState` (play/pause icon) and
`AvailableActions` (which controls are enabled).

## Control to API mapping

| Control | Action |
|---|---|
| Play/pause | `ActionId: "Play"` / `"Pause"`; the icon follows the pushed `PlayerState` |
| Previous / Next | `"PreviousTrack"` / `"NextTrack"`, enabled only when listed in `AvailableActions` |
| Shuffle / Repeat | `"Shuffle" {ShufState}` / `"Repeat" {RepState 0,1,2}` |
| Thumbs | `"ThumbsUp"` / `"ThumbsDown"`, shown only when `AvailableActions` lists them |
| Progress | local estimate between pushed `ElapsedSec` values; a click sends `"Seek" {Position}` only when `AvailableActions` lists `Seek` |
| Player picker | which `PlayerId` every player action and subscription uses |
| Selecting a service | `ProviderBrowseMenu` with `BrowseKey` = the provider key and no `SignedData` (root menu) |
| Opening a folder or card | `ProviderBrowseMenu` with the item's own `BrowseKey` and `SignedData` |
| Hero "Play" | `LoadSource` on the first playable item of the folder (a playlist itself cannot be loaded) |
| Load more | `ProviderBrowseMenu` on the last response's `ParentBrowseKey` (its `BrowseKey` and `SignedData`, unmodified) with the next `ItemOffset`; same for search results |
| Search | `SearchMenu`, one `SearchCategory` per request; the pills switch category |
| Playing a row | `LoadSource` with `ProfileKey`, `ProviderKey`, `AutoPlay: true` and the item's `SignedData` unmodified |
| Favorite (heart) | `AddFavorite` with the player's `SignedData` and `ProviderSave: false` (true also writes to the customer's streaming account), then the device prompt dialog for the name |
| Favorites list | `ListFavorites`; rename, delete and reorder with `RenameFavorite`, `DeleteFavorites`, `FavoriteMovePosition` |
