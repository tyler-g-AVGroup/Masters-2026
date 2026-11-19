"""Configuration mistakes students make on Windows get one clear message each."""

import json
import ssl
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from crestron.config import Config, load_config
from crestron.errors import DemoError
from crestron.mp2 import Mp2Client
from crestron.rest import RestClient

CLASSROOM = {
    "device_ip": "10.64.37.28:8443",
    "client_id": "classroom",
    "client_secret": "c2VjcmV0",
    "admin_user": "participant",
    "admin_password": "password",
    "verify_tls": False,
}


class ConfigTests(unittest.TestCase):
    def load(self, text, encoding="utf-8"):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_bytes(text.encode(encoding))
            return load_config(str(path))

    def test_byte_order_mark_and_surrounding_spaces_are_accepted(self):
        config = self.load(json.dumps(dict(CLASSROOM, device_ip=" 10.64.37.28:8443 ")), "utf-8-sig")
        self.assertEqual(config.device_ip, "10.64.37.28:8443")

    def test_bad_addresses_are_a_demo_error_not_a_traceback(self):
        for address in ("10.64.37.28:8443:8443", "10.64.37.28:port", "10.64.37.28:70000",
                        ":8443", "10.64.37.28:", "10.64.37.28:0", "10.64.\n37.28:8443"):
            with self.subTest(address), self.assertRaisesRegex(DemoError, "host:port"):
                self.load(json.dumps(dict(CLASSROOM, device_ip=address)))

    def test_hostnames_are_lowercased_and_ipv6_is_accepted(self):
        self.assertEqual(self.load(json.dumps(dict(CLASSROOM, device_ip="NAX-1.local:8443"))).device_ip,
                         "nax-1.local:8443")
        self.assertEqual(self.load(json.dumps(dict(CLASSROOM, device_ip="[fe80::1]:8443"))).device_ip,
                         "[fe80::1]:8443")

    def test_placeholder_names_the_file(self):
        with self.assertRaisesRegex(DemoError, r"Set device_ip in .*config\.json.*placeholder"):
            self.load(json.dumps(dict(CLASSROOM, device_ip=" <instructor-ip>:8443")))


class UntrustedCertificateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = Config("example.invalid", "c", "c2VjcmV0", "a", "p", verify_tls=True, timeout=1)
        self.failure = ssl.SSLCertVerificationError("self-signed certificate")

    async def test_mp2_reports_the_certificate_at_once(self):
        with patch("crestron.mp2.connect", side_effect=self.failure), patch(
            "crestron.mp2.asyncio.sleep"
        ) as sleep, self.assertRaisesRegex(DemoError, "MP2 certificate not trusted.*verify_tls"):
            await Mp2Client(self.config).open()
        sleep.assert_not_called()

    def test_rest_reports_the_certificate(self):
        client = RestClient(self.config)
        with patch.object(client.opener, "open", side_effect=urllib.error.URLError(self.failure)):
            with self.assertRaisesRegex(DemoError, "REST certificate not trusted.*verify_tls"):
                client._login()


if __name__ == "__main__":
    unittest.main()
