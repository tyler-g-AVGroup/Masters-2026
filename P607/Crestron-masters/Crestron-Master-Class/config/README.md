# config: your device settings

Every program reads `config/config.json` (or `--config <file>`).
Copy `config.example.json` to `config.json` and fill it in.

| Setting | Meaning |
| --- | --- |
| `device_ip` | `host` or `host:port`, for example `192.168.1.20:8443`. No `https://`. |
| `client_id`, `client_secret` | Media Player 2.0 client login. The secret is base64. |
| `admin_user`, `admin_password` | The device's web admin login, used for REST. |
| `service`, `folder` | Direct demo: which service and top folder to play from, for example `"Internet Radio"` and `"Popular stations"`. Default: the first signed-in service, every folder. |
| `player`, `zone` | Direct demo: the player (default `Player01`) and its zone. Without `zone`, exactly one zone must be reserved for the player. |
| `player_input` | The input `player` feeds. Needed when `player` isn't `Player01`. |
| `initial_seconds`, `resume_seconds` | Direct demo play times. Defaults 30 and 5; 1 to 300. |
| `timeout` | Seconds to wait for each reply. Default 12; 1 to 60. |
| `verify_tls` | Default `true`. `false` accepts a self-signed certificate: still encrypted, but the device's identity isn't checked, so only on a network you trust. |
