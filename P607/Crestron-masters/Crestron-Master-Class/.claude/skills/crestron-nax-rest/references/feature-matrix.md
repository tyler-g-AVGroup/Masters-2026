# DM NAX REST API feature matrix

Doc revision: May 13, 2025 (What's New). Hardware column: [B] = the main DM-NAX test unit; blank =
not tried. Paths are under `https://<ip>`; all writes are a
POST of a partial object to `/Device`.

## Session

| Feature | Request | Docs | Hardware |
|---|---|---|---|
| Log in | `GET /userlogin.html` (TRACKID cookie), then `POST /userlogin.html` form `login=<user>&passwd=<pass>` with `Origin` and `Referer` headers; keep the cookies and the `CREST-XSRF-TOKEN` response header | yes | yes [B]; wrong password = 403 |
| Write | `POST /Device` with JSON body and header `X-CREST-XSRF-TOKEN`; without it the device invalidates the session | yes | yes [B] |
| Read | `GET /Device/<Object>/<Path>` returns `{"Device":{...}}` for that path | yes | yes [B]; no session = 200 with the login page (HTML) |
| Change events (e.g. volume changed from a keypad) | `GET /Device/Longpoll` (or `/Device/<Object>/Longpoll`), or a WebSocket at `wss://<ip>/websockify` after login, which pushes changes | yes; message format not documented | |
| Log out | `GET /logout` | yes | sent [B]; effect not checked |

## Zones (`/Device/ZoneOutputs/Zones/ZoneX/`)

| Feature | Property | Docs | Hardware |
|---|---|---|---|
| Volume | `ZoneAudio/Volume`, 0 to 1000 (0.1 %); `VolumedB` read-only | yes | yes [B] |
| Mute | `ZoneAudio/IsMuted` | yes | yes [B] |
| Limits and startup level | `MinVolume` 0 to 500, `MaxVolume` 700 to 1000, `DefaultVolume` | yes | |
| Tone | `Bass`, `Treble` (-120 to 120, 0.1 dB), `Balance` (-500 to 500), `ToneProfile`, `IsLoudnessEnabled`, `NightMode` | yes | |
| EQ | `ZoneAudio/Peq/Bands/BandNN/{Gain,Frequency,Bandwidth,Type}` | yes | |
| Status | `IsSignalDetected`, `IsSignalClipping`, `Speaker/IsAmpOn`, `Speaker/Faults` | yes | `IsSignalDetected` yes [B] (lags a few seconds) |
| Name | `Name` (1 to 50 chars) | yes | |
| Which media player serves the zone | `ZoneBasedProviders/ReservedPlayer` (an `InputSources` key) | yes | yes [B]: zones reserve `MediaPlayer` inputs; read the mapping from the device |
| Do not disturb | `ZoneAudio/IsDndEnabled` | yes | |

## Routing and inputs

| Feature | Request | Docs | Hardware |
|---|---|---|---|
| Route a source to a zone | `/Device/AvMatrixRouting/Routes/<key>/AudioSource` = input id | yes, but the example keys (`output1`, `input1`) look generic | yes [B]: keys are the zone keys (`Zone1`, ...), value an input key; clearing removes the key |
| Auto routing | `/Device/AvMatrixRouting/IsAutomaticRoutingEnabled` | yes | read, not written [B]: named `IsAudioAutoRoutingEnabled`; effect on manual routes unknown |
| Mixer routing | `/Device/MatrixMixerRouting/MixerRoutes/OutputNNN/Inputs/InputNNN/{IsAudioRouted,GainLevel}` | yes; unclear which products use it for zones | |
| List inputs | `/Device/InputSources/Inputs/InputX` with `AudioType` (MediaPlayer, Digital, Analog, Aes67), `IsSignalPresent`, `Name` | yes | read [B] |
| Media player inputs | input slots after the physical inputs | stated, mapping to `PlayerNN` not documented | `Player01` = the first `MediaPlayer` input, confirmed [B]; the "NNth MediaPlayer input" rule is untested for other players |
| Grouped zones | `/Device/Bussing/Busses/BusNN` (bus `Volume` read-only, `IncludedZones`) | yes | |
| Stream to zone map | `/Device/NaxAudio/StreamReferenceMapping` | yes | |

## Not in this API

Playback, browsing, search and favorites: Media Player 2.0 (`crestron-mediaplayer-2`).
