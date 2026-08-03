"""Tests for agent.module_host (todo 3020 phase 3 / D9)."""

from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import agent.module_host as mh
from agent.module_host import (
    BACKEND_CONTRACT_VERSION,
    request_owner,
    run_vm_command,
    session,
)
from agent.tools.errors import CommandError

# Exception classes are referenced via the module (`mh.ModuleHostAuthError`)
# instead of a top-level import because ContractSurfaceTest reloads
# agent.module_host, which redefines the classes in place and would leave a
# stale pre-reload reference that `assertRaises` cannot match.


class ContractSurfaceTest(unittest.TestCase):
    def test_backend_contract_version_is_one(self):
        self.assertEqual(BACKEND_CONTRACT_VERSION, 1)

    def test_importing_module_host_does_not_import_paramiko(self):
        # Drop paramiko if a previous test imported it, then re-import the contract.
        sys.modules.pop("paramiko", None)
        # Force a fresh look at agent.module_host's module-level imports.
        import importlib
        import agent.module_host as mh

        importlib.reload(mh)
        self.assertNotIn("paramiko", sys.modules)


class SessionTest(unittest.TestCase):
    def test_session_is_thin_reexport_of_get_db(self):
        sentinel = object()

        class _CM:
            def __enter__(self):
                return sentinel

            def __exit__(self, *a):
                return False

        with patch("storage.database.base.get_db", return_value=_CM()) as get_db:
            with session() as s:
                self.assertIs(s, sentinel)
        get_db.assert_called_once_with()


class RunVmCommandTest(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_empty_argv(self):
        with request_owner(1):
            with self.assertRaises(ValueError):
                await run_vm_command(1, None, [])

    async def test_rejects_non_string_argv(self):
        with request_owner(1):
            with self.assertRaises(TypeError):
                await run_vm_command(1, None, ["y", 1])  # type: ignore[list-item]

    async def test_rejects_when_no_request_owner_bound(self):
        """review finding 2: without a bound request owner the capability refuses."""
        with self.assertRaises(mh.ModuleHostAuthError):
            await run_vm_command(1, None, ["y", "todo", "list"])

    async def test_rejects_caller_chosen_user_differing_from_bound_owner(self):
        """review finding 2: a module cannot steer execution at another user's id."""
        with request_owner(5):
            with self.assertRaises(mh.ModuleHostAuthError):
                await run_vm_command(7, None, ["y", "finance", "holdings"])

    async def test_raises_when_owner_has_no_vm_config(self):
        """review finding 2: no fallback to another (default) user's VM."""
        with request_owner(7), \
             patch("storage.service.vm_config.get_config", return_value=None) as get_cfg:
            with self.assertRaises(mh.ModuleVmNotConfiguredError):
                await run_vm_command(7, None, ["y", "todo", "list"])
        get_cfg.assert_called_once_with(7, "default")

    async def test_local_path_when_api_token_absent(self):
        vm = SimpleNamespace(api_token=None, work_dir="/tmp/work", vm_name="default")
        with request_owner(7), \
             patch("storage.service.vm_config.get_config", return_value=vm) as get_cfg, \
             patch("agent.tools.local_exec.local_exec", new_callable=AsyncMock, return_value="ok") as local, \
             patch("agent.tools.ssh_exec.ssh_exec", new_callable=AsyncMock) as ssh:
            out = await run_vm_command(7, None, ["y", "todo", "list"], timeout=12)
        self.assertEqual(out, "ok")
        get_cfg.assert_called_once_with(7, "default")
        local.assert_awaited_once()
        self.assertEqual(local.await_args.args[0], ["y", "todo", "list"])
        self.assertEqual(local.await_args.kwargs.get("timeout") or local.await_args.args[2], 12)
        self.assertTrue(local.await_args.kwargs.get("check"))
        ssh.assert_not_awaited()

    async def test_ssh_path_when_api_token_present(self):
        vm = SimpleNamespace(api_token="secret-key", work_dir="/home/roy", vm_name="ssh:roy@host")
        with request_owner(7), \
             patch("storage.service.vm_config.get_config", return_value=vm) as get_cfg, \
             patch("agent.tools.local_exec.local_exec", new_callable=AsyncMock) as local, \
             patch("agent.tools.ssh_exec.ssh_exec", new_callable=AsyncMock, return_value="remote") as ssh:
            out = await run_vm_command(7, "prod", ["y", "finance", "holdings"], timeout=45)
        self.assertEqual(out, "remote")
        get_cfg.assert_called_once_with(7, "prod")
        local.assert_not_awaited()
        ssh.assert_awaited_once()
        self.assertIs(ssh.await_args.args[0], vm)
        self.assertEqual(ssh.await_args.args[1], ["y", "finance", "holdings"])
        # timeout is keyword on ssh_exec
        self.assertEqual(ssh.await_args.kwargs.get("timeout"), 45)
        self.assertTrue(ssh.await_args.kwargs.get("check"))

    async def test_local_nonzero_exit_raises_command_error(self):
        """review finding 2: a failed local producer must look failed."""
        vm = SimpleNamespace(api_token=None, work_dir=None, vm_name="default")
        with request_owner(7), \
             patch("storage.service.vm_config.get_config", return_value=vm), \
             patch(
                 "agent.tools.local_exec.local_exec",
                 new_callable=AsyncMock,
                 side_effect=CommandError(1, "y finance refresh"),
             ):
            with self.assertRaises(CommandError) as ctx:
                await run_vm_command(7, None, ["y", "finance", "refresh"])
        self.assertEqual(ctx.exception.exit_code, 1)

    async def test_ssh_nonzero_exit_raises_command_error(self):
        """review finding 2: a failed SSH producer must look failed."""
        vm = SimpleNamespace(api_token="k", work_dir=None, vm_name="ssh:roy@host")
        with request_owner(7), \
             patch("storage.service.vm_config.get_config", return_value=vm), \
             patch(
                 "agent.tools.ssh_exec.ssh_exec",
                 new_callable=AsyncMock,
                 side_effect=CommandError(2, "y finance refresh"),
             ):
            with self.assertRaises(CommandError) as ctx:
                await run_vm_command(7, None, ["y", "finance", "refresh"])
        self.assertEqual(ctx.exception.exit_code, 2)

    async def test_error_propagates(self):
        vm = SimpleNamespace(api_token=None, work_dir=None, vm_name="default")
        with request_owner(1), \
             patch("storage.service.vm_config.get_config", return_value=vm), \
             patch(
                 "agent.tools.local_exec.local_exec",
                 new_callable=AsyncMock,
                 side_effect=RuntimeError("boom"),
             ):
            with self.assertRaises(RuntimeError):
                await run_vm_command(1, None, ["y", "todo", "list"])


if __name__ == "__main__":
    unittest.main()
