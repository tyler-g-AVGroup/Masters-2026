"""dmnax-server: a demo DM-NAX that answers this repo's clients without hardware.

Run:  python dmnax-server/server.py            (then open https://127.0.0.1:8443/)
Then: python demo_python/main.py --config dmnax-server/client-config.json

One TLS port serves everything a real DM-NAX would:
  wss://<host>/subscriptionmgr   Media Player 2.0 (players, browse, search, favorites)
  https://<host>/userlogin.html  REST login;  /Device/...  zone volume, mute, routing
  https://<host>/                live status page and fault switches (loopback only)
"""

import argparse
import asyncio
import datetime
import ipaddress
import json
import ssl
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from aiohttp import web  # noqa: E402

from device_model import DEFAULT_FAULTS, Device  # noqa: E402
from mp2_api import Mp2Hub  # noqa: E402
from rest_api import RestApi, json_response  # noqa: E402

# Demo credentials: public on purpose. The server checks them exactly as a device
# would (HMAC signature, admin password); they protect nothing real.
CLIENT_ID = "dmnax-demo-client"
CLIENT_SECRET = "ZG1uYXgtc2VydmVyLWRlbW8tc2VjcmV0LTAwMDE="  # base64
ADMIN_USER = "admin"
ADMIN_PASSWORD = "dmnax-demo"
HUB = web.AppKey("hub", Mp2Hub)
REST = web.AppKey("rest", RestApi)
TLS_DIR = HERE / ".tls"
CLIENT_CONFIG = HERE / "client-config.json"


def tls_context(directory=TLS_DIR):
    """A self-signed certificate, made once and reused (clients use verify_tls: false)."""
    cert, key = directory / "cert.pem", directory / "key.pem"
    if not (cert.exists() and key.exists()):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID

        directory.mkdir(parents=True, exist_ok=True)
        private = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "dmnax-server")])
        now = datetime.datetime.now(datetime.timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(private.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]), critical=False)
            .sign(private, hashes.SHA256())
        )
        key.write_bytes(private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(cert, key)
    return context


def client_config(device_ip):
    """Everything a client in this repo needs; nothing to fill in."""
    return {
        "device_ip": device_ip,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "admin_user": ADMIN_USER,
        "admin_password": ADMIN_PASSWORD,
        "player": "Player01",
        "zone": None,
        "service": "Internet Radio",
        "folder": "Popular stations",
        "verify_tls": False,
        "initial_seconds": 5,
        "resume_seconds": 3,
        "timeout": 12,
    }


def is_loopback(request):
    try:
        return ipaddress.ip_address(request.remote or "").is_loopback
    except ValueError:
        return False


def create_app(device):
    hub = Mp2Hub(device, CLIENT_ID, CLIENT_SECRET)
    rest = RestApi(device, ADMIN_USER, ADMIN_PASSWORD)
    status_page = (HERE / "status.html").read_text(encoding="utf-8")

    @web.middleware
    async def admin_only_from_loopback(request, handler):
        if (request.path == "/" or request.path.startswith("/dmnax/")) and not is_loopback(request):
            return web.Response(status=403, text="The status page answers loopback clients only.")
        return await handler(request)

    async def status(request):
        return web.Response(text=status_page, content_type="text/html")

    async def state(request):
        value = device.status()
        value["sessions"] = [
            {"session": s.id, "label": s.label, "connection": s.connection.id,
             "subscriptions": len(s.subscriptions)}
            for s in hub.sessions.values()
        ]
        value["rest_sessions"] = len(rest.sessions)
        return json_response(value)

    async def faults(request):
        try:
            body = await request.json()
        except ValueError:
            return json_response({"error": "JSON body expected"}, status=400)
        action = body.pop("action", None) if isinstance(body, dict) else None
        changed = {}
        for key, value in (body or {}).items():
            if key not in DEFAULT_FAULTS:
                return json_response({"error": "unknown fault '{}'".format(key)}, status=400)
            kind = type(DEFAULT_FAULTS[key])
            try:
                value = float(value) if kind is float else bool(value)
            except (TypeError, ValueError):
                return json_response({"error": "bad value for '{}'".format(key)}, status=400)
            device.faults[key] = changed[key] = value
        if changed:
            device.log("FAULT", "set {}".format(changed))
        if action == "drop_connections":
            device.log("FAULT", "dropping {} WebSocket connection(s)".format(len(hub.connections)))
            await hub.drop_all()
        elif action == "expire_rest_sessions":
            device.log("FAULT", "expired {} REST session(s)".format(rest.expire_all()))
        elif action:
            return json_response({"error": "unknown action '{}'".format(action)}, status=400)
        return json_response({"faults": device.faults})

    async def ticker(app):
        async def run():
            while True:
                device.tick()
                await asyncio.sleep(0.25)
        task = asyncio.ensure_future(run())
        yield
        task.cancel()
        await hub.drop_all()

    app = web.Application(middlewares=[admin_only_from_loopback])
    app.add_routes([
        web.get("/subscriptionmgr", hub.handle),
        web.get("/", status),
        web.get("/dmnax/api/state", state),
        web.post("/dmnax/api/faults", faults),
        *rest.routes(),
    ])
    app.cleanup_ctx.append(ticker)
    app[HUB], app[REST] = hub, rest
    return app


def parse_faults(values):
    faults = {}
    for value in values or []:
        key, _, raw = value.partition("=")
        if key not in DEFAULT_FAULTS:
            raise SystemExit("Unknown fault '{}'. Faults: {}".format(key, ", ".join(DEFAULT_FAULTS)))
        if isinstance(DEFAULT_FAULTS[key], float):
            faults[key] = float(raw or 1)
        else:
            faults[key] = raw.lower() not in ("0", "false", "off", "no") if raw else True
    return faults


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default="127.0.0.1",
                        help="address to listen on (default 127.0.0.1; the demo credentials are public)")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--players", type=int, default=5, help="media players (1-8)")
    parser.add_argument("--zones", type=int, default=5, help="zones (1-10)")
    parser.add_argument("--fault", action="append", metavar="NAME[=VALUE]",
                        help="start with a fault on: " + ", ".join(DEFAULT_FAULTS))
    parser.add_argument("--quiet", action="store_true", help="do not print the request log")
    args = parser.parse_args()

    device = Device(players=args.players, zones=args.zones, faults=parse_faults(args.fault),
                    log_to_console=not args.quiet)
    reachable = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    device_ip = reachable if args.port == 443 else "{}:{}".format(reachable, args.port)
    CLIENT_CONFIG.write_text(json.dumps(client_config(device_ip), indent=2) + "\n", encoding="utf-8")
    config_path = CLIENT_CONFIG.relative_to(HERE.parent)
    print("dmnax-server: DM-NAX-4ZSA demo, {} players, {} zones".format(args.players, args.zones))
    print("  status page   https://{}/   (self-signed certificate)".format(device_ip))
    print("  client config {}".format(config_path))
    print("  try           python demo_python/main.py --config {}".format(config_path))
    try:
        local = ipaddress.ip_address(reachable).is_loopback
    except ValueError:
        local = reachable == "localhost"
    if not local:
        print("  WARNING: listening beyond this machine with public demo credentials.")
    active = {k: v for k, v in device.faults.items() if v}
    if active:
        print("  faults on     {}".format(active))
    web.run_app(create_app(device), host=args.host, port=args.port,
                ssl_context=tls_context(), print=None)


if __name__ == "__main__":
    main()
