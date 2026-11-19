"""The menu client reports server teardown failure; the server does the cleanup pause."""

import argparse
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from demo_mcp.client import StdioClient, _run


class McpExitTests(unittest.IsolatedAsyncioTestCase):
    async def run_with_server_status(self, status, menu_run=None):
        process = types.SimpleNamespace(stdin=Mock(), wait=AsyncMock(), returncode=status)
        self.client = StdioClient(process)
        args = argparse.Namespace(config="unused.json")
        with patch("demo_mcp.client._start", AsyncMock(return_value=self.client)), patch(
            "demo_mcp.client.Menu.run", menu_run or AsyncMock()
        ), patch("sys.stderr", Mock()), patch("builtins.print"), patch("signal.signal"):
            return await _run(args)

    async def test_server_cleanup_failure_is_nonzero(self):
        self.assertEqual(await self.run_with_server_status(1), 1)

    async def test_clean_server_shutdown_returns_success(self):
        self.assertEqual(await self.run_with_server_status(0), 0)

    async def test_interrupt_still_closes_the_server_so_it_can_pause(self):
        async def interrupted(menu):
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            await self.run_with_server_status(0, menu_run=interrupted)
        self.client.process.stdin.close.assert_called_once()  # server shutdown pauses


class StdioClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_server_notification_between_requests_is_not_the_reply(self):
        lines = [
            b'{"jsonrpc":"2.0","method":"notifications/tools/list_changed"}\n',
            b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n',
        ]
        stdout = types.SimpleNamespace(readline=AsyncMock(side_effect=lines))
        stdin = types.SimpleNamespace(write=Mock(), drain=AsyncMock())
        client = StdioClient(types.SimpleNamespace(stdin=stdin, stdout=stdout))
        self.assertEqual(await client.request("tools/call", {}), {"ok": True})
