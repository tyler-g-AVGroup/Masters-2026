"""HTTPS REST session with restricted writes and read-back verification."""

import asyncio
import http.cookiejar
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from .errors import DemoError, SessionExpired
from .state import at_path


def has_empty_object(value):
    if value == {}:
        return True
    children = (
        value.values()
        if isinstance(value, dict)
        else value
        if isinstance(value, list)
        else []
    )
    return any(has_empty_object(child) for child in children)


def check_zone_version(version):
    """Volume is in tenths of a percent only from ZoneOutputs 2.0.15 on."""
    try:
        too_old = tuple(int(part) for part in str(version).split(".")) < (2, 0, 15)
    except ValueError:
        too_old = True
    if too_old:
        raise DemoError(
            "This device needs ZoneOutputs 2.0.15 or newer for 0.1% volume units."
        )


def read_reply(raw):
    value = raw.decode("utf-8-sig").strip()
    if value.startswith("<"):
        raise SessionExpired("REST session expired: device returned its login page.")
    try:
        reply = json.loads(value)
    except ValueError as exc:
        raise DemoError("Device returned an invalid REST response.") from exc
    if not isinstance(reply, dict):
        raise DemoError("Device returned a non-object REST response.")
    return reply


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # The login redirect carries the token we need to retain.


class RestClient:
    def __init__(self, config):
        self.config = config
        self.base = "https://" + config.device_ip
        self.headers = {"Origin": self.base, "Referer": self.base + "/userlogin.html"}
        jar = http.cookiejar.CookieJar()
        handlers = [
            urllib.request.HTTPSHandler(context=config.tls_context()),
            urllib.request.HTTPCookieProcessor(jar),
        ]
        self.opener = urllib.request.build_opener(NoRedirect(), *handlers)
        self.token = None
        self.lock = asyncio.Lock()

    def _no_answer(self):
        # urllib raises a bare timeout (not URLError) when the device accepts but never answers.
        return DemoError(
            "REST device did not answer within {:g} s; a write may or may not have applied.".format(
                self.config.timeout
            )
        )

    def _open(self, request):
        try:
            return self.opener.open(request, timeout=self.config.timeout)
        except socket.timeout as exc:  # TimeoutError on Python 3.10+
            raise self._no_answer() from exc
        except urllib.error.URLError as exc:
            if isinstance(exc, urllib.error.HTTPError):
                raise
            raise DemoError(
                "REST device unreachable: check the address and network ({})".format(
                    exc.reason
                )
            ) from exc

    def _login(self):
        with self._open(
            urllib.request.Request(self.base + "/userlogin.html", headers=self.headers)
        ):
            pass
        body = urllib.parse.urlencode(
            {"login": self.config.admin_user, "passwd": self.config.admin_password}
        ).encode()
        request = urllib.request.Request(
            self.base + "/userlogin.html",
            data=body,
            headers=self.headers,
            method="POST",
        )
        try:
            response = self._open(request)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            if response.code == 403:
                raise DemoError(
                    "REST login refused: check admin_user and admin_password."
                )
            self.token = response.headers.get("CREST-XSRF-TOKEN")
            if not self.token:
                raise DemoError(
                    "REST login returned no XSRF token (HTTP {}).".format(response.code)
                )

    async def _serial(self, function):
        async with self.lock:
            job = asyncio.ensure_future(
                asyncio.get_running_loop().run_in_executor(None, function)
            )
            try:
                return await asyncio.shield(job)
            except asyncio.CancelledError:
                # urllib cannot be cancelled mid-request. Keep the session lock
                # through repeated cancellation until its worker finishes.
                while not job.done():
                    try:
                        await asyncio.shield(job)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not job.cancelled():
                    job.exception()
                raise

    def _request(self, path, change=None):
        if not self.token:
            self._login()
        # An expired session answers 403 or with its HTML login page: log in once
        # and retry once, never in a loop.
        for attempt in range(2):
            headers = dict(self.headers)
            body = None
            if change is not None:
                if has_empty_object(change):
                    raise DemoError(
                        "Refusing an empty REST object: it would delete device configuration."
                    )
                headers.update(
                    {
                        "Content-Type": "application/json",
                        "X-CREST-XSRF-TOKEN": self.token,
                    }
                )
                body = json.dumps(change).encode()
            request = urllib.request.Request(
                self.base + path,
                body,
                headers,
                method="POST" if body is not None else "GET",
            )
            try:
                with self._open(request) as response:
                    return read_reply(response.read())
            except socket.timeout as exc:  # headers arrived, then the body stalled
                raise self._no_answer() from exc
            except urllib.error.HTTPError as exc:
                if exc.code != 403:
                    raise DemoError(
                        "REST request rejected (HTTP {}).".format(exc.code)
                    ) from exc
            except SessionExpired:
                pass
            if attempt == 0:
                self._login()
        raise SessionExpired("REST session expired again after one login retry.")

    async def get(self, path):
        if not path.startswith("/Device/") or ".." in path:
            raise DemoError("Invalid device read path.")
        return await self._serial(lambda: self._request(path))

    async def set_audio(self, zone, property_name, value):
        if property_name not in ("Volume", "IsMuted"):
            raise DemoError("This demo can write only zone volume and mute.")
        # Volume is in tenths of a percent (0 to 1000).
        if property_name == "Volume" and (
            type(value) is not int or not 0 <= value <= 1000
        ):
            raise DemoError("Volume must be an integer between 0 and 1000.")
        if property_name == "IsMuted" and type(value) is not bool:
            raise DemoError("Mute must be a boolean.")
        if (
            not isinstance(zone, str)
            or not zone.startswith("Zone")
            or not zone[4:].isdigit()
        ):
            raise DemoError("Invalid zone key.")

        def write_and_verify():
            change = {
                "Device": {
                    "ZoneOutputs": {
                        "Zones": {zone: {"ZoneAudio": {property_name: value}}}
                    }
                }
            }
            reply = self._request("/Device", change)
            results = [
                result
                for action in reply.get("Actions", [])
                for result in action.get("Results", [])
            ]
            if not results:
                raise DemoError("REST write has no Results; the change is unverified.")
            rejected = [item for item in results if item.get("StatusId", -4) != 0]
            if rejected:
                raise DemoError(
                    "REST device did not confirm the change: {}".format(rejected)
                )
            path = "/Device/ZoneOutputs/Zones/" + zone
            actual = at_path(self._request(path), path) or {}
            if actual.get("ZoneAudio", {}).get(property_name) != value:
                raise DemoError(
                    "REST read-back did not match {}={}.".format(property_name, value)
                )
            return actual

        return await self._serial(write_and_verify)

    async def close(self):
        if self.token:

            def logout():
                try:
                    try:
                        response = self._open(
                            urllib.request.Request(
                                self.base + "/logout", headers=self.headers
                            )
                        )
                    except urllib.error.HTTPError as exc:
                        if exc.code not in (301, 302, 303, 307, 308):
                            raise
                        response = exc  # Logout succeeded; never follow its redirect.
                    with response:
                        pass
                finally:
                    self.token = None

            await self._serial(logout)

    async def set_route(self, zone, source):
        """Used by tests/verify_live.py setup and by the approved set_route tool."""
        if (
            not isinstance(zone, str)
            or not zone.startswith("Zone")
            or not zone[4:].isdigit()
        ):
            raise DemoError("Invalid zone key.")
        if not isinstance(source, str):
            raise DemoError(
                "Route source must be a device input key or an empty string."
            )

        def write_and_verify():
            zones = (
                at_path(
                    self._request("/Device/ZoneOutputs"), "/Device/ZoneOutputs/Zones"
                )
                or {}
            )
            inputs = (
                at_path(
                    self._request("/Device/InputSources"), "/Device/InputSources/Inputs"
                )
                or {}
            )
            if zone not in zones or (source and source not in inputs):
                raise DemoError("Unknown route target or source; refusing to write.")
            change = {
                "Device": {
                    "AvMatrixRouting": {"Routes": {zone: {"AudioSource": source}}}
                }
            }
            reply = self._request("/Device", change)
            results = [
                item
                for action in reply.get("Actions", [])
                for item in action.get("Results", [])
            ]
            if not results or any(item.get("StatusId", -4) != 0 for item in results):
                raise DemoError("Device did not confirm the routing change.")
            routes = (
                at_path(
                    self._request("/Device/AvMatrixRouting"),
                    "/Device/AvMatrixRouting/Routes",
                )
                or {}
            )
            actual = routes.get(zone, {}).get("AudioSource", "")
            if actual != source:
                raise DemoError("Routing read-back did not match the requested input.")
            return actual

        return await self._serial(write_and_verify)
