# dmnax-server

A demo DM-NAX: a DM-NAX-4ZSA with 5 media players and 5 zones that answers every program in this
repo without hardware. How to install, run it, check it, use each client against it and make it
fail on purpose: **[Getting started](../docs/GETTING-STARTED.md)** (sections 2-6). This page is
the reference.

## What it serves

One TLS port (default 8443), at the same paths as a real device:

| Path | API | What it does |
| --- | --- | --- |
| `wss://<ip>/subscriptionmgr` | Media Player 2.0 | HMAC login check (`CrestronAuth-SHA256`), RegisterClient, GetCresNextObject, SubscribeToObject, pushes on subscribed paths, browse/search/home menus, ListFavorites, LoadSource and every transport action |
| `https://<ip>/userlogin.html`, `/Device/...`, `/logout` | REST | form login with `CREST-XSRF-TOKEN`, cookie sessions, `{"Device": ...}` reads, `Results`/`StatusId` on writes to zone volume, mute and routing |
| `https://<ip>/`, `/dmnax/api/state`, `/dmnax/api/faults` | demo only | status page, its JSON, fault switches (loopback clients only) |

It follows the public API docs. It does **not** copy the hardware quirks listed in the skills'
`api-gotchas.md` (blank `" "` fields, transient `AvailableActions: {}`, and so on). Passing
against it shows that a client and this server agree, not that the client works on hardware.

## Behavior worth knowing

- **Logins are real checks.** A wrong `client_secret` fails the WebSocket handshake (401), a wrong
  admin password gets 403, a write without the right `X-CREST-XSRF-TOKEN` gets 403.
- **SignedData is signed.** Every item's `SignedData` carries an HMAC over its `SourceData`; edited
  SignedData is refused. A song's SignedData also records the folder it was listed in, which
  becomes the play queue for NextTrack/PreviousTrack.
- **Like a device, a playlist can't be loaded with `LoadSource`**: open it and play a song inside it.
- **Playback runs on a clock.** Songs end and advance (shuffle and repeat apply); live stations
  (`Duration` 0) change their on-air line every 40 s. No audio is produced.
- **Paging:** 20 items per page. Popular stations (24) and the Big Mix playlist (45) page.
- **State lives in memory.** Restarting the server resets players, zones and faults.

## Options and files

`python dmnax-server/server.py [--host 127.0.0.1] [--port 8443] [--players 1-8] [--zones 1-10] [--fault NAME[=VALUE]]... [--quiet]`

Faults: `refuse_load`, `silent_player`, `reply_delay=<seconds>`, `reject_mp2_login`,
`reject_rest_login`, plus the actions `drop_connections` and `expire_rest_sessions` (API and
status page only). Effects: [Getting started, section 7](../docs/GETTING-STARTED.md#7-error-simulation).

| File | |
| --- | --- |
| `server.py` | entry point: TLS, routes, status/fault API, writes `client-config.json` |
| `mp2_api.py` | the WebSocket: login, sessions, subscriptions, the four command sets |
| `rest_api.py` | login, sessions, XSRF, reads and writes |
| `device_model.py` | the shared device state and the playback engine |
| `catalog.py` | profiles, services, menus, search, favorites, SignedData signing |
| `status.html` | the status page |
| `requirements.txt` | the three libraries it needs (`aiohttp`, `cryptography`, `websockets` for the tests) |
| `client-config.json`, `.tls/` | written on start; not committed |

Tests: `tests/test_dmnax_server.py` drives the real `Controller` and `Device` (the layer behind the
15 MCP tools) against an in-process server.
