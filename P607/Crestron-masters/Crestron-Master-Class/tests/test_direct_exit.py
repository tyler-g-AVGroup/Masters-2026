"""The direct CLI preserves primary errors when connection cleanup fails."""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from crestron.errors import DemoError
from demo_python import main


class DirectExitTests(unittest.TestCase):
    @staticmethod
    def plan():
        return {
            "device": {"model": "SIMULATOR", "firmware": "test"},
            "profile": {"key": "Profile1", "name": "Test profile"},
            "service": {"key": "Service1", "name": "Test service"},
            "player": "Player01",
            "input": "Input01",
            "zone": {"key": "Zone1", "name": "Test zone"},
            "initial_volume": 20,
            "track": {"title": "Test song", "browse_path": ["Test song"]},
            "routed": True,
            "initial_seconds": 2,
            "resume_seconds": 1,
        }

    def run_cli(self, controller):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("sys.argv", ["demo_python.main", "--config", "unused", "--check"]):
            with patch.object(main, "load_config", return_value=object()):
                with patch.object(main, "Controller", return_value=controller):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        result = main.main()
        return result, stdout.getvalue(), stderr.getvalue()

    def test_primary_preparation_error_survives_cleanup_error(self):
        class BrokenController:
            async def prepare(self):
                raise DemoError("primary preparation error")

            async def close(self):
                raise DemoError("secondary cleanup error")

        result, stdout, stderr = self.run_cli(BrokenController())
        self.assertEqual(result, 1)
        self.assertIn("Demo error: primary preparation error", stderr)
        self.assertIn("Connection cleanup failed: secondary cleanup error", stderr)
        self.assertNotIn("Demo error: secondary cleanup error", stderr)
        self.assertNotIn("Connections closed", stdout)

    def test_cleanup_only_error_is_reported_and_not_called_closed(self):
        class BrokenController:
            async def prepare(self):
                return DirectExitTests.plan()

            async def close(self):
                raise DemoError("cleanup only error")

        result, stdout, stderr = self.run_cli(BrokenController())
        self.assertEqual(result, 1)
        self.assertIn("Demo error: cleanup only error", stderr)
        self.assertNotIn("Connections closed", stdout)

    def test_success_reports_closed_only_after_successful_cleanup(self):
        class Controller:
            async def prepare(self):
                return DirectExitTests.plan()

            async def close(self):
                return None

        result, stdout, stderr = self.run_cli(Controller())
        self.assertEqual(result, 0)
        self.assertIn("Connections closed", stdout)
        self.assertEqual(stderr, "")

    def test_check_runs_with_windows_encoded_stdout(self):
        class Controller:
            async def prepare(self):
                return DirectExitTests.plan()

            async def close(self):
                return None

        with io.TextIOWrapper(io.BytesIO(), encoding="cp1252") as stdout:
            stderr = io.StringIO()
            with patch("sys.argv", ["demo_python.main", "--config", "unused", "--check"]):
                with patch.object(main, "load_config", return_value=object()):
                    with patch.object(main, "Controller", return_value=Controller()):
                        with redirect_stdout(stdout), redirect_stderr(stderr):
                            result = main.main()
            stdout.flush()
            output = stdout.buffer.getvalue().decode("cp1252")

        self.assertEqual(result, 0)
        self.assertIn("Sequence: play 2s -> pause -> volume 10% -> resume 1s -> pause", output)
        self.assertIn("Read-only check complete", output)
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
