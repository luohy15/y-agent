"""Unit tests for worktree uv environment provisioning (todo 3037)."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from yagent.commands.dev import worktree as wt_mod
from yagent.commands.dev.worktree import (
    _is_root_locked_uv_project,
    _provision_uv_env,
    wt_group,
)


class RootLockedUvProjectDetectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_requires_both_pyproject_and_lock(self):
        self.assertFalse(_is_root_locked_uv_project(self.path))

        Path(self.path, "pyproject.toml").write_text("[project]\nname='x'\n")
        self.assertFalse(_is_root_locked_uv_project(self.path))

        Path(self.path, "uv.lock").write_text("version = 1\n")
        self.assertTrue(_is_root_locked_uv_project(self.path))


class ProvisionUvEnvTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_skips_without_pyproject(self):
        Path(self.path, "uv.lock").write_text("version = 1\n")
        with patch.object(wt_mod.subprocess, "check_call") as check_call:
            _provision_uv_env(self.path)
        check_call.assert_not_called()

    def test_skips_without_uv_lock(self):
        Path(self.path, "pyproject.toml").write_text("[project]\nname='x'\n")
        with patch.object(wt_mod.subprocess, "check_call") as check_call:
            _provision_uv_env(self.path)
        check_call.assert_not_called()

    def test_runs_locked_sync_for_root_uv_project(self):
        Path(self.path, "pyproject.toml").write_text("[project]\nname='x'\n")
        Path(self.path, "uv.lock").write_text("version = 1\n")
        with patch.object(wt_mod.subprocess, "check_call") as check_call:
            _provision_uv_env(self.path)
        check_call.assert_called_once_with(
            ["uv", "sync", "--locked", "--project", self.path],
        )

    def test_removes_legacy_venv_symlink_before_sync(self):
        Path(self.path, "pyproject.toml").write_text("[project]\nname='x'\n")
        Path(self.path, "uv.lock").write_text("version = 1\n")
        target = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(target, ignore_errors=True))
        venv = Path(self.path) / ".venv"
        venv.symlink_to(target)
        self.assertTrue(venv.is_symlink())

        with patch.object(wt_mod.subprocess, "check_call") as check_call:
            _provision_uv_env(self.path)

        self.assertFalse(venv.exists())
        self.assertFalse(venv.is_symlink())
        check_call.assert_called_once_with(
            ["uv", "sync", "--locked", "--project", self.path],
        )

    def test_leaves_real_venv_directory_in_place(self):
        Path(self.path, "pyproject.toml").write_text("[project]\nname='x'\n")
        Path(self.path, "uv.lock").write_text("version = 1\n")
        venv = Path(self.path) / ".venv"
        venv.mkdir()
        (venv / "marker").write_text("keep\n")

        with patch.object(wt_mod.subprocess, "check_call") as check_call:
            _provision_uv_env(self.path)

        self.assertTrue(venv.is_dir())
        self.assertEqual((venv / "marker").read_text(), "keep\n")
        check_call.assert_called_once_with(
            ["uv", "sync", "--locked", "--project", self.path],
        )

    def test_subprocess_failure_propagates(self):
        Path(self.path, "pyproject.toml").write_text("[project]\nname='x'\n")
        Path(self.path, "uv.lock").write_text("version = 1\n")
        with patch.object(
            wt_mod.subprocess,
            "check_call",
            side_effect=subprocess.CalledProcessError(2, ["uv", "sync"]),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                _provision_uv_env(self.path)


class WtAddSetupOrderTest(unittest.TestCase):
    def _project(self, td: str) -> str:
        project = os.path.join(td, "proj")
        os.makedirs(os.path.join(project, ".git"))
        return project

    def test_hook_before_provision_before_registry(self):
        order: list[str] = []

        def run_hook(project_path, worktree_path, hook_name):
            order.append(f"hook:{hook_name}")

        def provision(worktree_path):
            order.append("provision")

        def create(*_args, **_kwargs):
            order.append("register")
            return {}

        with tempfile.TemporaryDirectory() as td:
            project = self._project(td)
            with (
                patch.object(wt_mod, "load_registry", return_value={}),
                patch.object(wt_mod.subprocess, "check_call"),
                patch.object(wt_mod, "_run_hook", side_effect=run_hook),
                patch.object(wt_mod, "_provision_uv_env", side_effect=provision),
                patch.object(wt_mod, "create_worktree", side_effect=create) as create_mock,
            ):
                result = CliRunner().invoke(wt_group, ["add", project, "test-wt"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(order, ["hook:post-create", "provision", "register"])
        create_mock.assert_called_once()

    def test_no_registry_write_when_provision_fails(self):
        with tempfile.TemporaryDirectory() as td:
            project = self._project(td)
            with (
                patch.object(wt_mod, "load_registry", return_value={}),
                patch.object(wt_mod.subprocess, "check_call"),
                patch.object(wt_mod, "_run_hook"),
                patch.object(
                    wt_mod,
                    "_provision_uv_env",
                    side_effect=subprocess.CalledProcessError(1, ["uv", "sync"]),
                ),
                patch.object(wt_mod, "create_worktree") as create_mock,
            ):
                result = CliRunner().invoke(wt_group, ["add", project, "test-wt"])

        self.assertNotEqual(result.exit_code, 0)
        create_mock.assert_not_called()

    def test_no_registry_write_when_hook_fails(self):
        with tempfile.TemporaryDirectory() as td:
            project = self._project(td)
            with (
                patch.object(wt_mod, "load_registry", return_value={}),
                patch.object(wt_mod.subprocess, "check_call"),
                patch.object(
                    wt_mod,
                    "_run_hook",
                    side_effect=subprocess.CalledProcessError(1, ["bash"]),
                ),
                patch.object(wt_mod, "_provision_uv_env") as provision_mock,
                patch.object(wt_mod, "create_worktree") as create_mock,
            ):
                result = CliRunner().invoke(wt_group, ["add", project, "test-wt"])

        self.assertNotEqual(result.exit_code, 0)
        provision_mock.assert_not_called()
        create_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
