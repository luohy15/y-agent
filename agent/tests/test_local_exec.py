"""Direct helper tests for agent.tools.local_exec (todo 3020 phase 3 review
finding 2 follow-up). test_module_host.py only mocks local_exec/ssh_exec, so
it proves propagation through run_vm_command but not the helpers' own
timeout/exit-status behaviour; these tests call local_exec() itself against
a real subprocess.
"""

from __future__ import annotations

import asyncio
import sys
import unittest

from agent.tools.errors import CommandError
from agent.tools.local_exec import local_exec


class LocalExecHelperTest(unittest.IsolatedAsyncioTestCase):
    async def test_success_returns_stdout(self):
        result = await local_exec([sys.executable, "-c", "print('hi')"], timeout=5)
        self.assertEqual(result.strip(), "hi")

    async def test_check_true_nonzero_exit_raises_command_error(self):
        with self.assertRaises(CommandError) as ctx:
            await local_exec(
                [sys.executable, "-c", "import sys; sys.exit(3)"], timeout=5, check=True
            )
        self.assertEqual(ctx.exception.exit_code, 3)

    async def test_check_false_nonzero_exit_does_not_raise(self):
        result = await local_exec(
            [sys.executable, "-c", "print('partial'); import sys; sys.exit(3)"],
            timeout=5,
            check=False,
        )
        self.assertEqual(result.strip(), "partial")

    async def test_check_false_timeout_propagates_instead_of_swallowing(self):
        """review finding 2 regression: check=False timeouts were silently
        swallowed into '' instead of surfacing to the caller, so a hung
        command on /api/terminal (check=False) looked like a successful
        empty result."""
        with self.assertRaises(asyncio.TimeoutError):
            await local_exec(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                timeout=0.2,
                check=False,
            )

    async def test_check_true_timeout_raises_command_error(self):
        with self.assertRaises(CommandError) as ctx:
            await local_exec(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                timeout=0.2,
                check=True,
            )
        self.assertEqual(ctx.exception.exit_code, -1)


if __name__ == "__main__":
    unittest.main()
