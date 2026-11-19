# Differences between the docs and real devices

Tag each entry with the device it was seen on, as in
`crestron-mediaplayer-2/references/api-gotchas.md`.

- **[B]** the main DM-NAX test unit (the same unit as [B] there).

## Hardware findings

- **No session = HTTP 200 with the login page, not 403.** [B] An unauthenticated
  `GET /Device/DeviceInfo` answered `200` with `Content-Type: text/html` (the web UI login page).
  A client that checks only the status code will try to parse HTML as JSON. Treat a non-JSON reply
  as "not logged in" and log in again. (The docs promise 403 for a missing or expired session.)
- **JSON replies are labelled `text/plain`.** [B] So the `Content-Type` header can't tell JSON from
  the HTML login page; check the body (HTML starts with `<`, after an optional UTF-8 BOM).
- **A wrong password returns 403** on the `POST /userlogin.html`. [B] Don't retry in a loop; one
  bad attempt was followed by a good one without a lockout, but lockout policy is unknown.
- **Route keys are the zone keys.** [B] `AvMatrixRouting/Routes` was keyed by zone (`Zone1`, ...; not the doc's
  `output1`), and `AudioSource` takes an `InputSources` key (`InputNN`). The write read back
  immediately.
- **Clearing a route deletes its key.** [B] Posting `{"AudioSource": ""}` for `Zone1` removed `Zone1`
  from `Routes`; `GET .../Routes/Zone1` then answered `{"Device": {}}`. Treat a missing route as "no
  source", and keep using the zone key to route again (posting to the missing key worked).
- **Auto-routing flag has a third name.** [B] The device reports `IsAudioAutoRoutingEnabled` (doc
  table: `IsAutomaticRoutingEnabled`, doc JSON: `IsAutomaticStreamRoutingEnabled`). It read `true`,
  yet every zone's `AudioSource` was `""` before the test.
- **Players map to `MediaPlayer` inputs.** [B] Media Player 2.0 `Player01` = the first `InputSources`
  entry with `AudioType: "MediaPlayer"`, confirmed by routing it to a zone, playing on `Player01` and
  seeing the zone's `IsSignalDetected` turn true.
  Read the keys and counts from the device.
- **Zone signal lags.** [B] `IsSignalDetected` turned true within a few seconds of play and stayed
  true for a few seconds after pause.
- **A muted zone reports no signal.** [B] With `IsMuted: true`, `IsSignalDetected` stayed `false`
  while Player01 was playing into the zone (seen once). So the flag cannot tell whether
  audio is still arriving at a muted zone: confirm a stop by asking Media Player 2.0 for the player's
  `PlayerState` instead.
- **Volume and mute read back at once.** [B] `ZoneAudio/Volume` 300 -> 200 -> 300 and `IsMuted`
  true -> false were visible on the next GET.

## Doc caveats (from reading, not hardware)

- The login sample code expects a `302` redirect to `/` on success, while the prose says `200 OK`.
  Accept either, and judge success by the `CREST-XSRF-TOKEN` header.
- The prose writes the login body as `login=<u>&&passwd=<p>` (double `&`); a standard form encoding
  with one `&` is assumed correct.
- The `AvMatrixRouting` example uses generic keys (`output1`, `input1`) and lists the auto-routing
  flag as `IsAutomaticStreamRoutingEnabled` in the JSON but `IsAutomaticRoutingEnabled` in the table.
  Read the device before writing.
- The mapping from Media Player 2.0 `PlayerNN` to an `InputSources` key is not documented.
- The docs list `StatusId` 2 (reset) and 3 (unsupported, "informational"); neither was seen on [B].
  Treat 3 as "not applied" and read the value back.
- The manual targets one DM NAX release; older firmware may lack newer properties (each object has a
  `Version`; check it).
