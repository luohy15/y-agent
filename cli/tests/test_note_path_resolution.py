import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner

from yagent.commands.assoc import assoc_link, assoc_note
from yagent.commands.entity.import_entity import entity_import
from yagent.commands.note.import_note import note_import, resolve_content_path
from yagent.commands.note.update import note_update


class NotePathResolutionCliTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.agent_home = Path(self.temp_dir.name) / "agent-home"
        self.pages_dir = self.agent_home / "pages"
        self.pages_dir.mkdir(parents=True)
        self.page = self.pages_dir / "example.md"
        self.page.write_text("---\nname: Example\ntype: project\n---\n\nHome copy\n")
        self.runner = CliRunner()
        self.env = {"Y_AGENT_HOME": str(self.agent_home)}

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_relative_paths_resolve_from_agent_home_not_cwd(self):
        with self.runner.isolated_filesystem():
            shadow = Path("pages")
            shadow.mkdir()
            (shadow / "example.md").write_text("Cwd shadow\n")

            with patch("yagent.commands.note.import_note.api_request") as api_request:
                api_request.return_value.json.return_value = {"note_id": "note-1"}
                result = self.runner.invoke(note_import, ["pages/example.md"], env=self.env)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Imported: pages/example.md -> note-1", result.output)
        payload = api_request.call_args.kwargs["json"]
        self.assertEqual(payload["content_key"], "pages/example.md")
        self.assertEqual(payload["front_matter"]["name"], "Example")

    def test_resolver_keeps_equivalent_absolute_and_relative_paths_identical(self):
        with patch.dict(os.environ, self.env, clear=False):
            relative = resolve_content_path("pages/example.md")
            absolute = resolve_content_path(self.page)
        self.assertEqual(relative, self.page.resolve())
        self.assertEqual(absolute, self.page.resolve())

    def test_note_update_has_identical_relative_and_absolute_content_keys(self):
        with self.runner.isolated_filesystem():
            with patch("yagent.commands.note.update.api_request") as api_request:
                api_request.return_value.json.return_value = {"note_id": "note-1", "content_key": "pages/example.md"}
                relative_result = self.runner.invoke(
                    note_update,
                    ["note-1", "--content-key", "pages/example.md"],
                    env=self.env,
                )
                absolute_result = self.runner.invoke(
                    note_update,
                    ["note-1", "--content-key", str(self.page)],
                    env=self.env,
                )

        self.assertEqual(relative_result.exit_code, 0, relative_result.output)
        self.assertEqual(absolute_result.exit_code, 0, absolute_result.output)
        relative_payload, absolute_payload = [call.kwargs["json"] for call in api_request.call_args_list]
        self.assertEqual(relative_payload["content_key"], "pages/example.md")
        self.assertEqual(relative_payload["content_key"], absolute_payload["content_key"])

    def test_entity_import_uses_agent_home_for_backing_note(self):
        note_response = Mock()
        note_response.json.return_value = {"note_id": "note-1"}
        entity_response = Mock()
        entity_response.json.return_value = {"entity_id": "entity-1"}
        link_response = Mock()

        with self.runner.isolated_filesystem():
            with patch("yagent.commands.note.import_note.api_request", return_value=note_response) as note_api_request, \
                 patch("yagent.commands.entity.import_entity.api_request", side_effect=[entity_response, link_response]) as api_request:
                result = self.runner.invoke(entity_import, ["pages/example.md"], env=self.env)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(note_api_request.call_args.kwargs["json"]["content_key"], "pages/example.md")
        self.assertEqual(api_request.call_args_list[0].kwargs["json"]["name"], "Example")

    def test_assoc_note_missing_file_exits_nonzero_without_relation_request(self):
        with self.runner.isolated_filesystem():
            with patch("yagent.commands.assoc.api_request") as api_request:
                result = self.runner.invoke(assoc_note, ["pages/missing.md", "--todo", "3019"], env=self.env)

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("File not found:", result.output)
        api_request.assert_not_called()

    def test_assoc_note_continues_after_failure_and_exits_nonzero(self):
        with self.runner.isolated_filesystem():
            with patch("yagent.commands.assoc.api_request") as api_request:
                result = self.runner.invoke(
                    assoc_note,
                    ["note-first", "pages/missing.md", "note-last", "--todo", "3019"],
                    env=self.env,
                )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Linked note note-first to todo 3019", result.output)
        self.assertIn("Linked note note-last to todo 3019", result.output)
        self.assertIn("File not found:", result.output)
        self.assertEqual(
            [call.kwargs["json"] for call in api_request.call_args_list],
            [
                {"note_id": "note-first", "todo_id": "3019"},
                {"note_id": "note-last", "todo_id": "3019"},
            ],
        )

    def test_assoc_link_uses_agent_home_file_instead_of_cwd_shadow(self):
        link_response = Mock()
        link_response.json.return_value = {"activity_id": "activity-1", "link_id": "link-1"}
        batch_response = Mock()
        batch_response.json.return_value = {"created": 1}

        with self.runner.isolated_filesystem():
            shadow = Path("pages")
            shadow.mkdir()
            (shadow / "example.md").write_text("Cwd shadow\n")

            with patch("yagent.commands.assoc.api_request", side_effect=[link_response, batch_response]) as api_request:
                result = self.runner.invoke(assoc_link, ["pages/example.md", "--todo", "3019"], env=self.env)

        self.assertEqual(result.exit_code, 0, result.output)
        payload = api_request.call_args_list[0].kwargs["json"]
        self.assertEqual(payload["path"], str(self.page.resolve()))
        self.assertIn("Home copy", payload["content"])


if __name__ == "__main__":
    unittest.main()
