# UI pattern: dark library

A dark, card-based music layout built from common streaming-app
conventions. Use the installed system font through CSS
(`system-ui, sans-serif`), generic inline SVG icons, and the dealer's brand
color as the single accent (default `#20b2c8`; never another product's
signature green, red or pink). Ship no logos, icons or fonts from other
products, and never name the app after another brand.

## Layout regions

- **Frame**: near-black background `#0b0c0f` with 8 px gaps between rounded
  (8 px) panels in `#15171c`.
- **Top bar** (56 px): home button on the left, a search field (40 px high,
  up to 480 px wide, fully rounded) in the center, the player picker and
  service picker on the right. Search is reachable from every page.
- **Player picker** (which `PlayerNN` this UI controls): list the `Players`
  keys, hide `ready` placeholders, default to the configured or first player,
  show each one's `PlayerState`.
- **Library panel** (left, 300 px): primary nav (Home, Search, Browse,
  Favorites), then the provider's root categories from the
  `ProviderBrowseMenu` root response, whatever it actually returns.
- **Main panel**: page content with a soft gradient (accent-tinted, 240 px
  tall) at the top fading into the panel color.
- **Home**: one section per `HomeScreenMenu` category, heading 22 px bold;
  folder items as a horizontally scrolling row of 180 px cards (square
  artwork, name, artist or kind); playable items as a numbered table. Artist
  items use circular artwork. Sections are empty until something has played;
  say so.
- **Folder page (album/playlist)**: hero header with 220 px artwork, kind
  label (12 px caps), title 40 px bold, artist and total item count (from
  `TotalItemCount`), and a 56 px round accent play button. Then a numbered
  table: # | Title (40 px artwork, title, artist beneath) | Album, rows 56 px.
- **Search**: category pills (32 px) under the top bar, results below; artist
  results as circular cards, songs as table rows. One `SearchMenu` request
  per selected category.
- **Player bar** (full width, 80 px, bottom): 56 px artwork and title/artist
  on the left, transport centered (play/pause 40 px round, white) with the
  progress line and times beneath, extras (thumbs, favorite) on the right.
- **Now Playing screen** (full screen, opened from the player's artwork or
  title, closed with a chevron or Esc): artwork up to 400 px over a blurred
  copy of it, title 28 px bold, artist, album, progress with times, the full
  transport (play/pause 64 px), thumbs and favorite, then one details line
  with the media type, the service name and any non-blank `Codec`/`BitRate`
  (present on the tested device but usually blank). The API has no queue
  read, so there is no queue view.
- **Device prompt dialog** (modal, 360 px, `#22252c`): shows any
  `Notification` from the player, navigation or favorites nodes: its message,
  a text field when `UserInputReq` is `Alphanumeric` (prefilled with
  `InitialUserInput`), and one button per `UserInputs` entry. Answer with the
  chosen input; close it when a `{"Notification": {}}` push arrives.
- **Artwork fallback**: when artwork is absent or not a plain http(s) URL,
  show a gradient tile with the item's initials.

## Sizes and states

- Colors: frame `#0b0c0f`, panels `#15171c`, hover `#22252c`, text `#ffffff`,
  secondary text `#a7adb8`, lines `#2a2d34`, accent = dealer color.
- Type: titles 40 px bold, section headings 22 px bold, body 14 px, captions
  12 px.
- Touch targets at least 44 px for touch panels; icon buttons 36 px.
- Hover: panel `#22252c` and the row's index turns into a play icon. Focus:
  2 px accent outline. Disabled (action not in `AvailableActions`; `Shuffle` and `Repeat` stay enabled): 35 %
  opacity, no pointer. Active toggles (shuffle, repeat on): accent color.
- Loading: keep the old list visible with a thin accent bar at the top; empty:
  one centered sentence; error: an inline banner with the device's message or
  a timeout notice.
- Progress: click to seek when `Seek` is listed; hide total time and progress
  line when `Duration` is 0 or less (live radio, or -1 while loading).
- Below 760 px wide: the library panel hides behind a menu button in the top
  bar; the table drops the Album column; the player bar keeps transport and
  title only.

## State fields shown

From `Player.NowPlayingData` (nested path in `../api-gotchas.md`): title
(trimmed `TrackTitle`, else trimmed `StationName`), artist, album, artwork,
`Duration`. From the player object: `PlayerState` (play/pause icon) and
`AvailableActions` (which controls are enabled).

## Control to API mapping

The same calls as the table in `light-list.md`; only the visual arrangement
differs.
