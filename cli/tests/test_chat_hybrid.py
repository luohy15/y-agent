"""Coverage for the built-in/module hybrid `y chat` command group."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import click
from click.testing import CliRunner

from yagent.commands.chat import click as chat_click


class ChatHybridGroupTest(unittest.TestCase):
    def test_latest_help_documents_module_dependency_and_fallbacks(self):
        with patch.object(chat_click.ChatHybridGroup, "_module_group", return_value=None):
            result = CliRunner().invoke(chat_click.chat_group, ["--help"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("active chat module list route", result.output)
        self.assertIn("-c for an explicit chat or -m for dispatch", result.output)

    def test_module_subcommand_is_delegated(self):
        @click.command("browse")
        def browse():
            click.echo("module browse")

        module_group = click.Group("chat", commands={"browse": browse})
        module = MagicMock(group=module_group)
        with (
            patch.object(chat_click, "source_dir", return_value=Path("/module/chat")),
            patch.object(Path, "is_file", return_value=True),
            patch.object(chat_click, "import_local_cli", return_value=module),
        ):
            result = CliRunner().invoke(chat_click.chat_group, ["browse"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("module browse", result.output)

    def test_dispatch_does_not_load_missing_module(self):
        with (
            patch.object(chat_click, "source_dir", return_value=Path("/missing/chat")),
            patch.object(Path, "is_file", return_value=False),
            patch.object(chat_click, "import_local_cli") as import_cli,
            patch.object(chat_click, "api_request") as request,
        ):
            request.return_value.json.return_value = {"chat_id": "dispatched"}
            result = CliRunner().invoke(
                chat_click.chat_group,
                ["-m", "ping", "--topic", "dev"],
                env={"Y_CHAT_ID": None},
            )
        self.assertEqual(result.exit_code, 0, result.output)
        import_cli.assert_not_called()
        request.assert_called_once_with(
            "POST",
            "/api/chat/notify",
            json={
                "message": "ping",
                "force_new": False,
                "from_topic": "manager",
                "topic": "dev",
            },
        )
        self.assertIn("dispatched", result.output)

    def test_interactive_latest_uses_module_list_route(self):
        response = MagicMock()
        response.json.return_value = [{"chat_id": "latest-chat"}]
        with (
            patch.object(chat_click, "api_request", return_value=response) as request,
            patch.object(chat_click, "DisplayManager"),
            patch.object(chat_click, "InputManager") as input_manager,
            patch.object(chat_click, "_stream_and_handle", return_value=(0, True)),
        ):
            input_manager.return_value.get_input.side_effect = KeyboardInterrupt
            result = CliRunner().invoke(chat_click.chat_group, ["-i", "--latest"])
        self.assertEqual(result.exit_code, 0, result.output)
        request.assert_called_once_with(
            "GET", "/api/module/chat/list", params={"limit": 1}
        )


if __name__ == "__main__":
    unittest.main()
