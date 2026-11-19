"""DM NAX REST (CresNext JSON over HTTPS).

GET  /userlogin.html   login page; sets TRACKID
POST /userlogin.html   form login=<user>&passwd=<password>; answers with the
                       CREST-XSRF-TOKEN header and an AuthByPasswd session cookie,
                       or 403 for a wrong login
GET  /Device/<path>    {"Device": {...}} for that path (403 without a session)
POST /Device           a JSON change; needs X-CREST-XSRF-TOKEN; answers
                       {"Actions": [{"Results": [{"StatusId": 0, ...}]}]}
GET  /logout           ends the session, redirects to the login page
"""

import asyncio
import hmac
import json
import secrets
import time

from aiohttp import web

from device_model import nest

LOGIN_PAGE = """<!doctype html><html><head><title>DM-NAX login (dmnax-server)</title></head>
<body><form method="post" action="/userlogin.html">
<input name="login" placeholder="user"> <input name="passwd" type="password">
<button>Sign in</button></form></body></html>"""


def json_response(value, status=200):
    return web.Response(status=status, text=json.dumps(value), content_type="application/json")


class RestApi:
    def __init__(self, device, admin_user, admin_password, session_seconds=1200):
        self.device = device
        self.admin_user, self.admin_password = admin_user, admin_password
        self.session_seconds = session_seconds
        self.sessions = {}  # AuthByPasswd cookie -> {"xsrf": token, "expires": t}

    def routes(self):
        return [
            web.get("/userlogin.html", self.login_page),
            web.post("/userlogin.html", self.login),
            web.get("/logout", self.logout),
            web.get("/Device", self.read),
            web.get("/Device/{tail:.*}", self.read),
            web.post("/Device", self.write),
        ]

    async def _delay(self):
        delay = self.device.faults.get("reply_delay") or 0
        if delay:
            await asyncio.sleep(float(delay))

    def _session(self, request):
        cookie = request.cookies.get("AuthByPasswd")
        session = self.sessions.get(cookie) if cookie else None
        if session and session["expires"] > time.time():
            session["expires"] = time.time() + self.session_seconds
            return cookie, session
        self.sessions.pop(cookie, None)
        return None, None

    def expire_all(self):
        count = len(self.sessions)
        self.sessions.clear()
        return count

    async def login_page(self, request):
        response = web.Response(text=LOGIN_PAGE, content_type="text/html")
        response.set_cookie("TRACKID", secrets.token_hex(8), path="/", secure=True, httponly=True)
        return response

    async def login(self, request):
        await self._delay()
        form = await request.post()
        user, password = str(form.get("login", "")), str(form.get("passwd", ""))
        good = (hmac.compare_digest(user, self.admin_user)
                and hmac.compare_digest(password, self.admin_password))
        if not good or self.device.faults.get("reject_rest_login"):
            self.device.log("REST", "login refused for '{}'".format(user))
            return web.Response(status=403, text="Forbidden")
        cookie, token = secrets.token_hex(16), secrets.token_hex(16)
        self.sessions[cookie] = {"xsrf": token, "expires": time.time() + self.session_seconds}
        self.device.log("REST", "login '{}' ok".format(user))
        response = web.Response(text="OK", headers={"CREST-XSRF-TOKEN": token})
        response.set_cookie("AuthByPasswd", cookie, path="/", secure=True, httponly=True)
        response.set_cookie("userid", user, path="/", secure=True)
        return response

    async def logout(self, request):
        cookie, _ = self._session(request)
        self.sessions.pop(cookie, None)
        redirect = web.HTTPFound("/userlogin.html")
        redirect.del_cookie("AuthByPasswd", path="/")
        raise redirect

    async def read(self, request):
        await self._delay()
        cookie, _ = self._session(request)
        if cookie is None:
            return web.Response(status=403, text="Session expired or missing; log in again")
        path = request.path.rstrip("/")
        value = self.device.read(path)
        if value is None:
            return json_response({"Error": "No such object: " + path}, status=404)
        return json_response(nest(path, value))

    async def write(self, request):
        await self._delay()
        cookie, session = self._session(request)
        if cookie is None:
            return web.Response(status=403, text="Session expired or missing; log in again")
        token = request.headers.get("X-CREST-XSRF-TOKEN", "")
        if not hmac.compare_digest(token, session["xsrf"]):
            self.device.log("REST", "write refused: bad X-CREST-XSRF-TOKEN")
            return web.Response(status=403, text="Bad X-CREST-XSRF-TOKEN")
        try:
            change = json.loads(await request.text() or "{}")
        except ValueError:
            return web.Response(status=400, text="Body is not valid JSON")
        results = self.device.rest_write(change)
        return json_response({"Actions": [{"Operation": "SetPartial", "TargetObject": "Device",
                                           "Results": results}]})
