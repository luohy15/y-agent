"""Tests for api.controller.file's safe-rename path (todo 2888): the
_SAFE_RENAME_SCRIPT subprocess helper (path/new_name validation, traversal
escape rejection, collision + case-only-rename handling, apply on file and
directory) and the rename_file endpoint (status mapping, the note-pointer
guard, and the two-phase resolve/apply call sequence).

Plain unittest (no pytest) so this runs under the CI unittest runner.
"""

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


def run_safe_rename(agent_home: Path, work_dir: Path, mode: str, requested_path: str, new_name: str) -> dict:
    result = subprocess.run(
        ["python3", "-c", file_controller._SAFE_RENAME_SCRIPT, mode, requested_path, new_name, str(agent_home)],
        cwd=work_dir,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


class SafeRenameScriptTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

    def test_resolve_returns_content_key(self):
        agent_home = self.tmp_path / "agent-home"
        work_dir = agent_home / "project"
        work_dir.mkdir(parents=True)
        (work_dir / "a.txt").touch()

        result = run_safe_rename(agent_home, work_dir, "resolve", "a.txt", "b.txt")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["content_key"], "project/a.txt")
        self.assertFalse(result["is_dir"])
        self.assertTrue((work_dir / "a.txt").exists())  # resolve does not touch fs

    def test_rejects_traversal_and_parent_symlink_escape(self):
        agent_home = self.tmp_path / "agent-home"
        work_dir = agent_home / "project"
        outside_dir = self.tmp_path / "outside"
        work_dir.mkdir(parents=True)
        outside_dir.mkdir()
        (outside_dir / "outside.txt").touch()
        (work_dir / "escape").symlink_to(outside_dir, target_is_directory=True)

        self.assertEqual(run_safe_rename(agent_home, work_dir, "resolve", "../../outside/outside.txt", "x.txt")["status"], "invalid")
        self.assertEqual(run_safe_rename(agent_home, work_dir, "resolve", "escape/outside.txt", "x.txt")["status"], "invalid")

    def test_missing_source(self):
        agent_home = self.tmp_path / "agent-home"
        work_dir = agent_home / "project"
        work_dir.mkdir(parents=True)

        self.assertEqual(run_safe_rename(agent_home, work_dir, "resolve", "missing.txt", "x.txt")["status"], "missing")

    def test_existing_target_is_a_collision(self):
        agent_home = self.tmp_path / "agent-home"
        work_dir = agent_home / "project"
        work_dir.mkdir(parents=True)
        (work_dir / "a.txt").touch()
        (work_dir / "b.txt").touch()

        self.assertEqual(run_safe_rename(agent_home, work_dir, "resolve", "a.txt", "b.txt")["status"], "exists")

    def test_agent_home_itself_is_unsupported(self):
        agent_home = self.tmp_path / "agent-home"
        agent_home.mkdir(parents=True)

        result = run_safe_rename(agent_home, agent_home, "resolve", str(agent_home), "renamed")
        self.assertEqual(result["status"], "unsupported")

    def test_new_name_validation(self):
        agent_home = self.tmp_path / "agent-home"
        work_dir = agent_home / "project"
        work_dir.mkdir(parents=True)
        (work_dir / "a.txt").touch()

        for bad_name in ("", "a/b", ".."):
            self.assertEqual(run_safe_rename(agent_home, work_dir, "resolve", "a.txt", bad_name)["status"], "invalid")

    def test_same_name_is_unchanged(self):
        agent_home = self.tmp_path / "agent-home"
        work_dir = agent_home / "project"
        work_dir.mkdir(parents=True)
        (work_dir / "a.txt").touch()

        self.assertEqual(run_safe_rename(agent_home, work_dir, "resolve", "a.txt", "a.txt")["status"], "unchanged")

    def test_apply_renames_a_file(self):
        agent_home = self.tmp_path / "agent-home"
        work_dir = agent_home / "project"
        work_dir.mkdir(parents=True)
        (work_dir / "a.txt").write_text("keep")

        result = run_safe_rename(agent_home, work_dir, "apply", "a.txt", "b.txt")
        self.assertEqual(result["status"], "renamed")
        self.assertFalse((work_dir / "a.txt").exists())
        self.assertEqual((work_dir / "b.txt").read_text(), "keep")

    def test_apply_renames_a_directory(self):
        agent_home = self.tmp_path / "agent-home"
        work_dir = agent_home / "project"
        src_dir = work_dir / "olddir"
        src_dir.mkdir(parents=True)
        (src_dir / "inner.txt").write_text("keep")

        result = run_safe_rename(agent_home, work_dir, "apply", "olddir", "newdir")
        self.assertEqual(result["status"], "renamed")
        self.assertTrue(result["is_dir"])
        self.assertFalse(src_dir.exists())
        self.assertEqual((work_dir / "newdir" / "inner.txt").read_text(), "keep")


class RenameEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_failure_maps_status_and_skips_note_guard(self):
        async def run_with_output(*args, **kwargs):
            return json.dumps({"status": "missing", "detail": "File does not exist"})

        with (
            patch.object(file_controller, "_exec", run_with_output),
            patch.object(file_controller.note_service, "list_notes_at_path") as list_notes,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await file_controller.rename_file(_request(), file_controller.RenameRequest(path="missing.txt", new_name="b.txt"))

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "File does not exist")
        list_notes.assert_not_called()

    async def test_note_guard_blocks_with_409_and_no_apply_call(self):
        commands = []

        async def run_with_output(*args, **kwargs):
            commands.append(args[1])
            return json.dumps({"status": "ok", "content_key": "pages/plan-2888-filetree-rename.md", "is_dir": False})

        blocking_note = SimpleNamespace(content_key="pages/plan-2888-filetree-rename.md")
        with (
            patch.object(file_controller, "_exec", run_with_output),
            patch.object(file_controller.note_service, "list_notes_at_path", return_value=[blocking_note]),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await file_controller.rename_file(_request(), file_controller.RenameRequest(path="pages/plan-2888-filetree-rename.md", new_name="renamed.md"))

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("pages/plan-2888-filetree-rename.md", ctx.exception.detail)
        self.assertEqual(len(commands), 1)  # only the resolve call, no apply

    async def test_happy_path_issues_resolve_then_apply_and_echoes_new_path(self):
        commands = []

        async def run_with_output(*args, **kwargs):
            commands.append(args[1])
            if args[1][3] == "resolve":
                return json.dumps({"status": "ok", "content_key": "sub/a.txt", "is_dir": False})
            return json.dumps({"status": "renamed", "content_key": "sub/b.txt", "is_dir": False})

        with (
            patch.object(file_controller, "_exec", run_with_output),
            patch.object(file_controller.note_service, "list_notes_at_path", return_value=[]),
        ):
            result = await file_controller.rename_file(_request(), file_controller.RenameRequest(path="sub/a.txt", new_name="b.txt"))

        self.assertEqual(result, {"path": "sub/a.txt", "new_path": "sub/b.txt", "renamed": True})
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][3], "resolve")
        self.assertEqual(commands[1][3], "apply")


if __name__ == "__main__":
    unittest.main()
