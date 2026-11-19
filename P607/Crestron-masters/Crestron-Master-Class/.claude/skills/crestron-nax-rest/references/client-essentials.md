# Client essentials

Any language's standard HTTPS client with a cookie store is enough. The pieces below are the parts
that matter, as steps; implement them in the project's language.

## 1. Login

TLS without checking the device's self-signed certificate (`verify_tls: false`, the usual case;
keep checks on if the device has a trusted certificate): turn off both
hostname and certificate-chain checks; the connection is still encrypted and no certificate file is
needed. `device_ip`, `admin_user` and `admin_password` come from the config file. Base URL
`https://<device_ip>`; send `Origin: <base>` and `Referer: <base>/userlogin.html` on every request.

1. `GET /userlogin.html` and keep the `TRACKID` cookie it sets.
2. `POST /userlogin.html` with `Content-Type: application/x-www-form-urlencoded` and the body
   `login=<admin_user>&passwd=<admin_password>` (URL-encode each value).
   Do not follow the redirect it answers with: the redirect reply itself carries the token.
3. HTTP 403: login refused, report "check the admin username and password" and do not retry in a
   loop.
4. Read the `CREST-XSRF-TOKEN` response header. Missing: fail with "login gave no CREST-XSRF-TOKEN"
   and the HTTP status.

Keep every cookie the device sets (`AuthByPasswd`, `TRACKID`, `iv`, `tag`, `userid`, `userstr`) in a
cookie store and send them on later requests; `AuthByPasswd` changes on later replies, so update it
from each reply. `GET /logout` ends the session.

## 2. Read, write, check

Reading a reply (both GET and POST):

1. Check the HTTP status first. 403 is the documented "session expired" answer: raise a distinct
   "session expired" error. Any other non-2xx status is a plain failure: report it, do not parse
   the body.
2. Decode the body as UTF-8 and drop a leading byte-order mark and surrounding whitespace.
3. Body starts with `<`: the session is gone ([B]: a missing session returned 200 with the HTML
   login page; expiry untested). Same "session expired" error as step 1.
4. Otherwise parse it as JSON (empty body = `{}`). JSON arrives labelled `text/plain`, so never
   decide by the `Content-Type` header.

Reading: `GET /Device/<path>`, e.g. `/Device/ZoneOutputs/Zones/Zone1`.

Writing: `POST /Device` with the JSON change, `Content-Type: application/json` and
`X-CREST-XSRF-TOKEN: <token>`.

1. Before sending, walk the whole change (objects and arrays, every depth). If the change itself,
   or any value in it, is an empty object `{}`, refuse with an error: the device would delete that object. Use a real error, not a
   debug-only assertion that a release build can strip.
2. Collect every `Results` entry under every `Actions` entry of the reply.
3. Any `StatusId < 0`: the device refused; report the results.
4. Any `StatusId == 3` (documented as "unsupported"): not applied; report it as a failure.
5. Any `StatusId == 1`: tell the user the device needs a restart for the change to take effect.
6. A success status is not proof: read the value back with a GET.

On "session expired", log in once more and retry the call once.
Write only what you mean to change, then read it back, e.g. set
`{"Device":{"ZoneOutputs":{"Zones":{"Zone1":{"ZoneAudio":{"Volume":200}}}}}}` and GET the zone.
Keep a fixed allowlist of the properties your app may write; never forward user or page JSON.

## 3. Player to input to zone

A Media Player 2.0 `PlayerNN` is not named in this API. Per the InputSources doc, media players take
the input slots after the physical inputs, with `AudioType: "MediaPlayer"`. Working rule:
`PlayerNN` = the NNth `MediaPlayer` input in key order. Confirmed only for `Player01` = the first `MediaPlayer`
input, on the test unit; confirm other players on hardware before relying on it. Each zone names the
input that serves it in `ZoneBasedProviders/ReservedPlayer`. To confirm: play on the player (Media
Player 2.0) and check that input's `IsSignalPresent` and the zone's `IsSignalDetected`.

## 4. Routing

Read `/Device/AvMatrixRouting` first. On the test unit the route keys are the zone keys and
`AudioSource` is an input key: `{"Device":{"AvMatrixRouting":{"Routes":{"Zone1":{"AudioSource":"<InputNN>"}}}}}`.
Clearing (`""`) removes the zone's key from `Routes`, so read a missing route as "no source". Save the
current `AudioSource` before changing it so it can be restored.

## 5. Live-system etiquette

- Before a test, check nobody is using the zone: its player idle and `IsSignalDetected` false.
- Save, change, read back, restore. Set a quiet level (20 % or lower, never above the saved level; if
  `MinVolume` is above 20 %, use `MinVolume` or ask the user) before routing any audio.
- Before a test also check no other zone has the same input routed (the song would play there too),
  and don't test in a zone that is muted on purpose.
- Clean up in this order: mute the zone; stop playback with Media Player 2.0 `Pause` (the device
  ignores `Stop`) and wait for `PlayerState` `paused` or `stopped`; restore the route and the volume;
  restore the saved mute state only once the player reports `paused` or `stopped`, otherwise leave the zone muted
  and report it. Run each step even if an earlier one fails, and report failures instead of hiding them.
- Never change other zones, bussing, zone configuration, impedance or speaker power without being
  asked: those can damage speakers or take a room offline.
