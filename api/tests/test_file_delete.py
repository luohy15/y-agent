"""Tests for api.controller.file's safe-delete path (todo 2831): the
_SAFE_UNLINK_SCRIPT subprocess helper (path validation, traversal/symlink
escape rejection, directory refusal, symlink unlink without following
target) and the delete_file endpoint (status mapping, agent_home passed
API-side).

Plain unittest (no pytest) so this runs under the CI unittest runner.
"""

import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from api.controller import file as file_controller


def _request(user_id=1):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id))


def run_safe_unlink(agent_home: Path, work_dir: Path, requested_path: str) -> dict:
    result = subprocess.run(
        ["python3", "-c", file_controller._SAFE_UNLINK_SCRIPT, requested_path, str(agent_home)],
        cwd=work_dir,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


class SafeUnlinkScriptTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

    def test_accepts_relative_and_absolute_paths(self):
        agent_home = self.tmp_path / "agent-home"
        work_dir = agent_home / "project"
        work_dir.mkdir(parents=True)
        relative_file = work_dir / "relative.txt"
        absolute_file = work_dir / "absolute.txt"
        relative_file.touch()
        absolute_file.touch()

        self.assertEqual(run_safe_unlink(agent_home, work_dir, "relative.txt")["status"], "deleted")
        self.assertFalse(relative_file.exists())
        self.assertEqual(run_safe_unlink(agent_home, work_dir, str(absolute_file))["status"], "deleted")
        self.assertFalse(absolute_file.exists())

    def test_rejects_outside_root_and_parent_symlink(self):
        agent_home = self.tmp_path / "agent-home"
        work_dir = agent_home / "project"
        outside_dir = self.tmp_path / "outside"
        work_dir.mkdir(parents=True)
        outside_dir.mkdir()
        outside_file = outside_dir / "outside.txt"
        outside_file.touch()
        (work_dir / "escape").symlink_to(outside_dir, target_is_directory=True)

        self.assertEqual(run_safe_unlink(agent_home, work_dir, "../../outside/outside.txt")["status"], "invalid")
        self.assertTrue(outside_file.exists())
        self.assertEqual(run_safe_unlink(agent_home, work_dir, "escape/outside.txt")["status"], "invalid")
        self.assertTrue(outside_file.exists())

    def test_refuses_missing_directories_and_root(self):
        agent_home = self.tmp_path / "agent-home"
        work_dir = agent_home / "project"
        work_dir.mkdir(parents=True)
        directory = work_dir / "directory"
        directory.mkdir()

        self.assertEqual(run_safe_unlink(agent_home, work_dir, "missing.txt")["status"], "missing")
        self.assertEqual(run_safe_unlink(agent_home, work_dir, "directory")["status"], "unsupported")
        self.assertTrue(directory.exists())
        self.assertEqual(run_safe_unlink(agent_home, work_dir, str(agent_home))["status"], "unsupported")

    def test_removes_symlink_without_touching_target(self):
        agent_home = self.tmp_path / "agent-home"
        work_dir = agent_home / "project"
        outside_dir = self.tmp_path / "outside"
        work_dir.mkdir(parents=True)
        outside_dir.mkdir()
        target = outside_dir / "target.txt"
        target.write_text("keep")
        link = work_dir / "link.txt"
        link.symlink_to(target)

        self.assertEqual(run_safe_unlink(agent_home, work_dir, "link.txt")["status"], "deleted")
        self.assertFalse(link.exists())
        self.assertEqual(target.read_text(), "keep")


class DeleteEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def test_maps_target_results(self):
        async def run_with_output(*args, **kwargs):
            return json.dumps({"status": "missing", "detail": "File does not exist"})

        with patch.object(file_controller, "_exec", run_with_output):
            with self.assertRaises(HTTPException) as ctx:
                await file_controller.delete_file(_request(), file_controller.DeleteRequest(path="missing.txt"))

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "File does not exist")

    async def test_passes_api_agent_home(self):
        commands = []

        async def run_with_output(*args, **kwargs):
            commands.append(args[1])
            return json.dumps({"status": "deleted"})

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            with (
                patch.object(file_controller, "_exec", run_with_output),
                patch.object(file_controller, "Y_AGENT_HOME", tmp_path),
            ):
                result = await file_controller.delete_file(_request(), file_controller.DeleteRequest(path="file.txt"))

        self.assertEqual(result, {"path": "file.txt", "deleted": True})
        self.assertEqual(commands, [["python3", "-c", file_controller._SAFE_UNLINK_SCRIPT, "file.txt", str(tmp_path)]])


if __name__ == "__main__":
    unittest.main()
