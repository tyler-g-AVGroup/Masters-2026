# crestron: the library

Everything that talks to the device; the four client folders call it. No entry point of its own.

- Depends on: `websockets` (Python 3.8+).
- Used by: `demo_python/`, `demo_mcp/`, `demo_mcp_http/`, `demo_mcp_sdk/`, `tests/`.

## How the code flows

```mermaid
flowchart TD
    A["demo_python"] --> C["Controller<br/>controller.py"]
    B["demo_mcp, demo_mcp_sdk and demo_mcp_http"] --> D["Device<br/>device.py"]
    C --> M["Mp2Client<br/>mp2.py"]
    C --> R["RestClient<br/>rest.py"]
    D --> M
    D --> R
    M -- "WebSocket: browse, play, pause" --> X["DM-NAX"]
    R -- "HTTPS: volume, mute, routing" --> X
```

Every change is two steps: send it, then wait for the device to prove it happened.

**Play or pause (`mp2.py`).** Send the command, then wait for a device push that arrived after it (`controller.py`, `_transport`):

```python
baseline = await self.mp2.action(self.config.player, action)
await self.mp2.wait_player(self.config.player, baseline, expected)
```

**Volume (`rest.py`).** Write it, then read it back (`set_audio`):

```python
reply = self._request("/Device", change)
# ...
actual = at_path(self._request(path), path) or {}
if actual.get("ZoneAudio", {}).get(property_name) != value:
    raise DemoError(
        "REST read-back did not match {}={}.".format(property_name, value)
    )
```

**Login.** MP2 signs its WebSocket handshake with the shared secret (`auth_header`). REST logs in with user and password and gets a cookie and an XSRF token (`_login`).

**Which function sends which API call:**

| Function | API call |
| --- | --- |
| `Mp2Client.open` | WebSocket connect, then `RegisterClient` |
| `Mp2Client.get` | `GetCresNextObject` |
| `Mp2Client.subscribe` | `SubscribeToObject` |
| `Mp2Client.browse`, `navigate` | `MediaNavigation` (browse, search, home screen) |
| `Mp2Client.favorites` | `MediaFavorites` `ListFavorites` |
| `Mp2Client.load_source`, `action` | `MediaPlayerNeXt` `LoadSource`, `Play`, `Pause`, ... |
| `RestClient.get` | `GET /Device/...` (logs in first if needed) |
| `RestClient.set_audio`, `set_route` | `POST /Device`, then a `GET` to read back |
| `RestClient.close` | `GET /logout` |

Real requests and replies: [demo_python/README.md](../demo_python/README.md#api-calls-to-the-device).

## Files

| File | What it does |
| --- | --- |
| `config.py` | Loads and checks `config/config.json` (the default every program uses). |
| `mp2.py` | Media Player 2.0 WebSocket client: signed login, subscriptions, browse, play, pause. |
| `rest.py` | DM-NAX REST client: login, XSRF token, zone reads and verified writes. |
| `state.py` | Player state from MP2 pushes, and small helpers for device JSON. |
| `device.py` | Every MCP tool's reads, previews and verified changes. |
| `controller.py`, `workflow.py` | The direct demo's discovery and its fixed script. |
| `console.py` | Terminal output for the direct demo. |
| `errors.py` | `DemoError`: the one error type the programs print instead of a traceback. |
