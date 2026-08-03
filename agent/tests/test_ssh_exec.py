"""Direct helper tests for agent.tools.ssh_exec (todo 3020 phase 3 review
finding 2 follow-up). test_module_host.py only mocks local_exec/ssh_exec, so
it proves propagation through run_vm_command but not the helper's own
timeout/exit-status/client-close behaviour. These tests drive ssh_exec()
itself against a fake paramiko.SSHClient (real paramiko would need a live
SSH server), including a real blocking read in the executor thread so the
"cannot cancel the executor thread, so force-close the client instead"
fix is actually exercised.
"""

from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import Mock, patch

from agent.tools.errors import CommandError
from agent.tools.ssh_exec import ssh_exec
from storage.dto.vm import VmConfig


class _FakeChannel:
    def __init__(self, exit_status: int = 0):
        self._exit_status = exit_status

    def recv_exit_status(self) -> int:
        return self._exit_status


class _FakeStream:
    def __init__(self, payload: bytes = b"", channel=None, delay: float = 0.0):
        self._payload = payload
        self.channel = channel
        self._delay = delay

    def read(self) -> bytes:
        if self._delay:
            # Runs in the real executor thread: stands in for a remote
            # command that has not produced output yet. The outer
            # asyncio.wait_for cannot stop this thread, only abandon it.
            time.sleep(self._delay)
        return self._payload

    def write(self, data) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeSSHClient:
    """Stands in for paramiko.SSHClient so the timeout/exit-status paths in
    ssh_exec() run for real, without a live SSH server."""

    def __init__(self, stdout: bytes = b"ok\n", exit_status: int = 0, read_delay: float = 0.0):
        self.stdout = stdout
        self.exit_status = exit_status
        self.read_delay = read_delay
        self.closed = False
        self.connected = False

    def set_missing_host_key_policy(self, policy) -> None:
        pass

    def connect(self, *a, **kw) -> None:
        self.connected = True

    def exec_command(self, cmd, timeout=None):
        channel = _FakeChannel(self.exit_status)
        stdin_ch = _FakeStream(channel=channel)
        stdout_ch = _FakeStream(self.stdout, channel=channel, delay=self.read_delay)
        stderr_ch = _FakeStream(b"", channel=channel)
        return stdin_ch, stdout_ch, stderr_ch

    def close(self) -> None:
        self.closed = True


def _vm() -> VmConfig:
    return VmConfig(vm_name="ssh:roy@host", api_token="fake-key", work_dir="")


class SshExecHelperTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._patches = [
            patch("agent.tools.ssh_exec.ensure_and_touch_vm"),
            patch("agent.tools.ssh_exec.paramiko.Ed25519Key.from_private_key", return_value=Mock()),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def _install_client(self, **kwargs) -> _FakeSSHClient:
        client = _FakeSSHClient(**kwargs)
        patcher = patch("agent.tools.ssh_exec.paramiko.SSHClient", return_value=client)
        patcher.start()
        self.addCleanup(patcher.stop)
        return client

    async def test_success_returns_stdout(self):
        self._install_client(stdout=b"hello\n", exit_status=0)
        result = await ssh_exec(_vm(), ["echo", "hello"], timeout=5)
        self.assertEqual(result, "hello\n")

    async def test_check_true_nonzero_exit_raises_command_error(self):
        """review finding 2: a failed SSH producer must look failed, on the
        real ssh_exec() path (not through a mocked wrapper)."""
        self._install_client(stdout=b"", exit_status=3)
        with self.assertRaises(CommandError) as ctx:
            await ssh_exec(_vm(), ["false"], timeout=5, check=True)
        self.assertEqual(ctx.exception.exit_code, 3)

    async def test_check_false_nonzero_exit_does_not_raise(self):
        self._install_client(stdout=b"partial\n", exit_status=3)
        result = await ssh_exec(_vm(), ["false"], timeout=5, check=False)
        self.assertEqual(result, "partial\n")

    async def test_check_false_timeout_propagates_instead_of_swallowing(self):
        """Regression: check=False timeouts were silently swallowed into ''
        instead of surfacing to the caller."""
        client = self._install_client(stdout=b"never\n", exit_status=0, read_delay=0.3)
        with self.assertRaises(asyncio.TimeoutError):
            await ssh_exec(_vm(), ["sleep", "5"], timeout=0.05, check=False)
        self.assertTrue(client.closed, "client must be force-closed on timeout even with check=False")

    async def test_check_true_timeout_raises_command_error_and_closes_client(self):
        """asyncio.wait_for cannot cancel the executor thread blocked inside
        paramiko's read(); the fix force-closes the client from the timeout
        handler instead of leaking the connection until the thread happens
        to finish on its own."""
        client = self._install_client(stdout=b"never\n", exit_status=0, read_delay=0.3)
        with self.assertRaises(CommandError) as ctx:
            await ssh_exec(_vm(), ["sleep", "5"], timeout=0.05, check=True)
        self.assertEqual(ctx.exception.exit_code, -1)
        self.assertTrue(client.closed, "client must be closed on timeout despite the still-running executor thread")


if __name__ == "__main__":
    unittest.main()
