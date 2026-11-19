"""Shared Crestron <-> Python bridge for server.py.

Python -> Crestron : send()/log() wrap module_info.set(json). The C# callback gets
                     every message; {"debug": "..."} lines go to CrestronConsole.PrintLine.
Crestron -> Python : module_info.subscribe(); each JSON string is parsed and passed
                     to the handler. {"Running": "False"} stops the module.
No threading.Event/Lock waits: the stop flag is a plain attribute that is polled
(see simpleMcpServer_diag.py for why).
"""
import json
import os
import sys
import time

# python/ root: makes the helpers and crestron packages and the top-level modules importable from the module host.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# Vendored pure-Python packages (aiohttp, websockets, ...): see lib/.
_LIB = os.path.join(ROOT, "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)


class Bridge:
    def __init__(self, module_info, name):
        self.module_info = module_info
        self.name = name
        self.running = True

    def send(self, data):
        data = dict(data)
        data["uid"] = self.module_info.uid
        data["from"] = self.name
        self.module_info.set(json.dumps(data, default=str), saved=True)

    def log(self, text):
        """Show up in CrestronConsole via the C# callback."""
        try:
            self.send({"debug": "[{}] {}".format(self.name, text)})
        except Exception:
            pass

    def listen(self, handler):
        """handler(msg: dict) runs for each JSON message from Crestron."""

        def on_message(val):
            try:
                msg = json.loads(val)
            except (ValueError, TypeError):
                self.log("bad JSON from Crestron: {}".format(val))
                return
            if not isinstance(msg, dict):
                return
            if str(msg.get("Running")).lower() == "false":
                self.running = False
                return
            try:
                handler(msg)
            except Exception as exc:
                self.log("handler error: {}".format(exc))

        self.module_info.subscribe(on_message)

    def wait(self):
        while self.running:
            time.sleep(0.5)
