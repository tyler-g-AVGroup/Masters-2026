import asyncio
import io
import socket
import sys
import threading
import unittest
import urllib.error
from unittest.mock import patch

from crestron.config import Config
from crestron.errors import DemoError, SessionExpired
from crestron.rest import RestClient, has_empty_object, read_reply


def configuration(address="example.invalid"):
    return Config(address, "client", "c2VjcmV0", "admin", "password", timeout=1)


def in_thread(function, *args):
    # asyncio.to_thread needs Python 3.9; the library supports 3.8.
    return asyncio.get_running_loop().run_in_executor(None, function, *args)


def cancel(task, reason):
    # Task.cancel(msg) needs Python 3.9.
    return task.cancel(reason) if sys.version_info >= (3, 9) else task.cancel()


class RestTests(unittest.IsolatedAsyncioTestCase):
    def test_reject_empty_objects_at_any_depth(self):
        self.assertTrue(has_empty_object({"Device": {"Zones": [{"Zone1": {}}]}}))
        self.assertFalse(has_empty_object({"Device": {"Volume": 100}}))

    def test_html_login_page_is_expired_session_even_with_http_200(self):
        with self.assertRaises(SessionExpired):
            read_reply(b"\xef\xbb\xbf  <html>login</html>")
        self.assertEqual(read_reply(b'{"Device": {}}'), {"Device": {}})

    async def test_volume_scale_payload_and_readback_are_verified(self):
        client = RestClient(configuration())
        calls = []

        def request(path, change=None):
            calls.append((path, change))
            if change is not None:
                return {"Actions": [{"Results": [{"StatusId": 0}]}]}
            return {
                "Device": {
                    "ZoneOutputs": {"Zones": {"Zone1": {"ZoneAudio": {"Volume": 100}}}}
                }
            }

        client._request = request
        await client.set_audio("Zone1", "Volume", 100)
        self.assertEqual(
            calls[0][1]["Device"]["ZoneOutputs"]["Zones"]["Zone1"]["ZoneAudio"][
                "Volume"
            ],
            100,
        )
        self.assertEqual(calls[1][0], "/Device/ZoneOutputs/Zones/Zone1")

    async def test_unsupported_results_or_mismatched_readback_are_errors(self):
        for status in (-1, 3, 0):
            client = RestClient(configuration())

            def request(path, change=None):
                if change is not None:
                    return {"Actions": [{"Results": [{"StatusId": status}]}]}
                return {
                    "Device": {
                        "ZoneOutputs": {
                            "Zones": {"Zone1": {"ZoneAudio": {"Volume": 300}}}
                        }
                    }
                }

            client._request = request
            with self.assertRaises(DemoError):
                await client.set_audio("Zone1", "Volume", 100)

    async def test_arbitrary_properties_and_boolean_volume_are_refused(self):
        for property_name, value in (("SpeakerPower", True), ("Volume", True)):
            client = RestClient(configuration())
            with self.assertRaises(DemoError):
                await client.set_audio("Zone1", property_name, value)

    async def test_repeated_cancellation_holds_lock_until_worker_finishes(self):
        client = RestClient(configuration())
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        second_started = threading.Event()

        def first_worker():
            started.set()
            try:
                if not release.wait(3):
                    raise AssertionError("First worker was not released")
                return 200
            finally:
                finished.set()

        def second_worker():
            second_started.set()
            self.assertTrue(finished.is_set(), "REST workers overlapped")
            return 300

        first = asyncio.create_task(client._serial(first_worker))
        second = None
        try:
            self.assertTrue(await in_thread(started.wait, 3))
            second = asyncio.create_task(client._serial(second_worker))
            for reason in ("request timeout", "tab closed", "shutdown"):
                self.assertTrue(cancel(first, reason))
                await asyncio.sleep(0)  # Deliver each cancellation before the next.
                self.assertFalse(first.done())
                self.assertTrue(client.lock.locked())
                self.assertFalse(second_started.is_set())
            release.set()
            with self.assertRaises(asyncio.CancelledError) as cancelled:
                await asyncio.wait_for(first, 3)
            if sys.version_info >= (3, 11):  # 3.8-3.10 drop the reason on this path
                self.assertEqual(cancelled.exception.args, ("request timeout",))
            self.assertEqual(await asyncio.wait_for(second, 3), 300)
            self.assertTrue(finished.is_set())
            self.assertFalse(client.lock.locked())
        finally:
            release.set()
            tasks = [first] + ([second] if second is not None else [])
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 3)
            self.assertTrue(await in_thread(finished.wait, 3))

    async def test_repeated_cancellation_cannot_overwrite_later_verified_volume(self):
        client = RestClient(configuration())
        started = threading.Event()
        release = threading.Event()
        first_read_back = threading.Event()
        state = {"Volume": 100}
        applied, verified = [], []

        def request(path, change=None):
            if change is not None:
                volume = change["Device"]["ZoneOutputs"]["Zones"]["Zone1"]["ZoneAudio"][
                    "Volume"
                ]
                if volume == 200:
                    started.set()
                    if not release.wait(3):
                        raise AssertionError("First write was not released")
                state["Volume"] = volume
                applied.append(volume)
                return {"Actions": [{"Results": [{"StatusId": 0}]}]}
            volume = state["Volume"]
            verified.append(volume)
            if volume == 200:
                first_read_back.set()
            return {
                "Device": {
                    "ZoneOutputs": {"Zones": {"Zone1": {"ZoneAudio": {"Volume": volume}}}}
                }
            }

        client._request = request
        first = asyncio.create_task(client.set_audio("Zone1", "Volume", 200))
        second = None
        try:
            self.assertTrue(await in_thread(started.wait, 3))
            for reason in ("request timeout", "tab closed", "shutdown"):
                cancel(first, reason)
                await asyncio.sleep(0)
            second = asyncio.create_task(client.set_audio("Zone1", "Volume", 300))
            if first.done():
                # Expose an early unlock: verify 300 before the stale 200 resumes.
                await asyncio.wait_for(second, 3)
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(first, 3)
            actual = await asyncio.wait_for(second, 3)
            self.assertTrue(await in_thread(first_read_back.wait, 3))
            self.assertEqual(actual["ZoneAudio"]["Volume"], 300)
            self.assertEqual(applied, [200, 300])
            self.assertEqual(verified, [200, 300])
            self.assertEqual(state["Volume"], 300)
        finally:
            release.set()
            tasks = [first] + ([second] if second is not None else [])
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 3)
            self.assertTrue(await in_thread(first_read_back.wait, 3))

    async def test_repeated_cancellation_retrieves_worker_error_and_keeps_original_cancel(self):
        client = RestClient(configuration())
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        failure = DemoError("Worker failed")
        loop = asyncio.get_running_loop()
        run_in_executor = loop.run_in_executor
        jobs = []

        def submit(executor, function):
            job = run_in_executor(executor, function)
            jobs.append(job)
            return job

        def worker():
            started.set()
            try:
                if not release.wait(3):
                    raise AssertionError("Failing worker was not released")
                raise failure
            finally:
                finished.set()

        with patch.object(loop, "run_in_executor", side_effect=submit):
            task = asyncio.create_task(client._serial(worker))
            await asyncio.sleep(0)
        job = jobs[0]
        with patch.object(job, "exception", wraps=job.exception) as retrieve:
            try:
                self.assertTrue(await in_thread(started.wait, 3))
                for reason in ("request timeout", "tab closed", "shutdown"):
                    cancel(task, reason)
                    await asyncio.sleep(0)
                release.set()
                with self.assertRaises(asyncio.CancelledError) as cancelled:
                    await asyncio.wait_for(task, 3)
                self.assertFalse(job.cancelled())
                retrieve.assert_called()
                self.assertIs(job.exception(), failure)
                if sys.version_info >= (3, 11):  # 3.8-3.10 drop the reason on this path
                    self.assertEqual(cancelled.exception.args, ("request timeout",))
                self.assertFalse(client.lock.locked())
            finally:
                release.set()
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 3)
                self.assertTrue(await in_thread(finished.wait, 3))

    async def test_serial_preserves_normal_results_and_errors(self):
        client = RestClient(configuration())
        self.assertEqual(await asyncio.wait_for(client._serial(lambda: 200), 3), 200)
        failure = DemoError("Worker failed")

        def worker():
            raise failure

        with self.assertRaises(DemoError) as raised:
            await asyncio.wait_for(client._serial(worker), 3)
        self.assertIs(raised.exception, failure)
        self.assertFalse(client.lock.locked())
        self.assertEqual(await asyncio.wait_for(client._serial(lambda: 300), 3), 300)

    async def test_logout_redirect_is_not_followed_or_reported_as_failure(self):
        client = RestClient(configuration())
        client.token = "token"
        calls = []

        def open_request(request):
            calls.append(request.full_url)
            raise urllib.error.HTTPError(
                request.full_url, 301, "Moved", {"Location": "/"}, io.BytesIO()
            )

        client._open = open_request
        await client.close()
        self.assertEqual(calls, ["https://example.invalid/logout"])
        self.assertIsNone(client.token)

    async def test_a_device_that_accepts_but_never_answers_is_a_demo_error(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        held = []  # keep the accepted socket open and silent
        threading.Thread(target=lambda: held.append(listener.accept()), daemon=True).start()
        client = RestClient(configuration())
        # Plain HTTP so the connection completes and only the reply is missing.
        client.base = "http://127.0.0.1:{}".format(listener.getsockname()[1])
        client.token = "token"
        try:
            with self.assertRaisesRegex(DemoError, "did not answer within 1 s"):
                await asyncio.wait_for(client.get("/Device/DeviceInfo"), 10)
        finally:
            listener.close()
            for connection, _ in held:
                connection.close()
