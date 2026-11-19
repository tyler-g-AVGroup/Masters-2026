"""MP2 browse must surface a device refusal instead of timing out."""

import asyncio
import unittest

from crestron.config import Config
from crestron.errors import DemoError
from crestron.mp2 import Mp2Client


class BrowseRefusalTests(unittest.IsolatedAsyncioTestCase):
    async def test_notification_without_msgid_is_reported_as_the_answer(self):
        config = Config("example.invalid", "client", "c2VjcmV0", "a", "p", timeout=2)
        client = Mp2Client(config)
        client.session = "s1"
        reply = {
            "Device": {
                "MediaNavigation": {
                    "RegisteredClientMenus": {
                        "s1": {
                            "Notification": {
                                "NotiId": "n1",
                                "Widget": {"Msg": '{"code":"CERT_HAS_EXPIRED"}'},
                            }
                        }
                    }
                }
            }
        }

        class Socket:
            async def send(self, text):
                # Deliver the device's reply the way the receive loop would.
                for predicate, future in list(client.pending):
                    if not future.done() and predicate(reply):
                        future.set_result(reply)

        client.socket = Socket()
        with self.assertRaisesRegex(DemoError, "CERT_HAS_EXPIRED"):
            await asyncio.wait_for(client.browse("Profile1", "Provider10"), 5)

    async def test_refusal_echoing_another_request_is_not_taken(self):
        config = Config("example.invalid", "client", "c2VjcmV0", "a", "p", timeout=1)
        client = Mp2Client(config)
        client.session = "s1"
        stale = {
            "Device": {
                "MediaNavigation": {
                    "RegisteredClientMenus": {
                        "s1": {
                            "LastRequestAction": {"MsgId": "older-request"},
                            "Notification": {"Msg": "late refusal"},
                        }
                    }
                }
            }
        }

        class Socket:
            async def send(self, text):
                for predicate, _ in list(client.pending):
                    self.matched = predicate(stale)

        client.socket = Socket()
        with self.assertRaisesRegex(DemoError, "timed out"):
            await client.browse("Profile1", "Provider10")
        self.assertFalse(client.socket.matched)

    async def test_overlapping_snapshot_reads_keep_the_path_marked_until_the_last_reply(self):
        # A polled ElapsedSec=0 must not reset the running timer: while any read of
        # the path is outstanding, its replies are still snapshots, not pushes.
        config = Config("example.invalid", "client", "c2VjcmV0", "a", "p", timeout=5)
        client = Mp2Client(config)
        client.session = "s1"
        path = "/Device/MediaPlayerNeXt/Players"
        reply = {"Device": {"MediaPlayerNeXt": {"Players": {"Player01": {"PlayerState": "playing"}}}}}

        class Socket:
            async def send(self, text):
                pass

        def deliver():
            for predicate, future in list(client.pending):
                if not future.done() and predicate(reply):
                    future.set_result(reply)

        client.socket = Socket()
        first = asyncio.ensure_future(client.get(path))
        second = asyncio.ensure_future(client.get(path))
        await asyncio.sleep(0.3)
        deliver()
        await first
        self.assertIn(path, client.snapshot_paths)  # the second read is still pending
        await asyncio.sleep(0.3)
        deliver()
        await second
        self.assertEqual(client.snapshot_paths, {})

    def test_malformed_notification_text(self):
        from crestron.mp2 import notice_text

        self.assertEqual(notice_text({"Widget": None}), "device notification")
        self.assertEqual(notice_text("busy"), "busy")


if __name__ == "__main__":
    unittest.main()
