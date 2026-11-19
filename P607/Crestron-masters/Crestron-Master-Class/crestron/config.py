"""Configuration is loaded locally; credentials are never printed."""

import base64
import json
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from .errors import DemoError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = str(ROOT / "config" / "config.json")


@dataclass
class Config:
    device_ip: str
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    admin_user: str = field(repr=False)
    admin_password: str = field(repr=False)
    player: str = "Player01"
    zone: Optional[str] = None
    service: Optional[str] = None
    folder: Optional[str] = None
    player_input: Optional[str] = None
    verify_tls: bool = True
    initial_seconds: int = 30
    resume_seconds: int = 5
    timeout: float = 12.0

    def tls_context(self):
        context = ssl.create_default_context()
        if not self.verify_tls:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        return context


def load_config(path=DEFAULT_CONFIG):
    try:
        # utf-8-sig: Notepad and Windows PowerShell 5.1 may save a byte-order mark.
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise DemoError("Cannot read configuration {}: {}".format(path, exc)) from exc
    if not isinstance(data, dict):
        raise DemoError("Configuration must be a JSON object.")
    required = (
        "device_ip",
        "client_id",
        "client_secret",
        "admin_user",
        "admin_password",
    )
    for key in required:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or value.strip().startswith("<"):
            raise DemoError(
                "Set {} in {}; it is empty or still a <placeholder>.".format(key, path)
            )
    # Host names are case-insensitive, and the MP2 signature covers this exact text.
    data["device_ip"] = data["device_ip"].strip().lower()
    # Accept an IP address or hostname with an optional port, never a URL or API path.
    if any(char in data["device_ip"] for char in "/?#@"):
        raise DemoError(
            "device_ip must be an IP address or hostname, without a URL scheme."
        )
    try:
        address = urlsplit("//" + data["device_ip"])
        if (
            not address.hostname
            or data["device_ip"].endswith(":")
            or any(not char.isprintable() or char.isspace() for char in data["device_ip"])
            or address.port == 0
        ):
            raise ValueError()
    except ValueError:  # urlsplit raises it for a port that is not 1 to 65535
        raise DemoError(
            "device_ip must be host or host:port, for example 192.168.1.20:8443."
        )
    try:
        if not base64.b64decode(data["client_secret"], validate=True):
            raise ValueError()
    except ValueError:
        raise DemoError("client_secret must be a nonempty base64 value.")
    values = {key: data[key] for key in required}
    for key in (
        "player",
        "zone",
        "service",
        "folder",
        "player_input",
        "verify_tls",
        "initial_seconds",
        "resume_seconds",
        "timeout",
    ):
        if key in data:
            values[key] = data[key]
    config = Config(**values)
    if not isinstance(config.verify_tls, bool):
        raise DemoError("verify_tls must be true or false.")
    if not isinstance(config.player, str) or not config.player.startswith("Player"):
        raise DemoError("player must name a device player, such as Player01.")
    if config.zone is not None and (
        not isinstance(config.zone, str) or not config.zone
    ):
        raise DemoError("zone must name a device zone, such as Zone1, or be null.")
    for key in ("service", "folder"):
        value = getattr(config, key)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise DemoError("{} must be a name or null.".format(key))
        if value is not None:
            setattr(config, key, value.strip())
    for key in ("initial_seconds", "resume_seconds"):
        value = getattr(config, key)
        if type(value) is not int or not 1 <= value <= 300:
            raise DemoError("{} must be an integer from 1 to 300.".format(key))
    if (
        isinstance(config.timeout, bool)
        or not isinstance(config.timeout, (int, float))
        or not 1 <= config.timeout <= 60
    ):
        raise DemoError("timeout must be between 1 and 60 seconds.")
    return config
