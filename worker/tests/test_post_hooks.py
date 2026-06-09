"""Unit tests for worker.runner post-completion hooks.

Covers _run_post_hooks dispatch + _hook_save_plan_to_todo, the plan->todo-note
hook that parses the final assistant message for a plan path and writes it to the
todo's progress. todo_service is mocked; nothing touches a real database.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from worker import runner


def _chat(messages):
    return SimpleNamespace(messages=messages)


def _msg(role, content):
    return SimpleNamespace(role=role, content=content)


class HookSavePlanToTodoTest(unittest.TestCase):
    def test_extracts_last_md_path_and_updates_todo(self):
        chat = _chat([
            _msg("user", "please plan it"),
            _msg("assistant", "Wrote the plan to /Users/roy/luohy15/pages/plan-2480.md done."),
        ])
        with patch("storage.service.todo.update_todo") as update_todo:
            runner._hook_save_plan_to_todo(chat, {"todo_id": "2480"}, user_id=123)
        update_todo.assert_called_once_with(123, "2480", progress="/Users/roy/luohy15/pages/plan-2480.md")

    def test_uses_last_path_when_multiple_present(self):
        chat = _chat([
            _msg("assistant", "see /tmp/a.md and then /tmp/final.md"),
        ])
        with patch("storage.service.todo.update_todo") as update_todo:
            runner._hook_save_plan_to_todo(chat, {"todo_id": "9"}, user_id=1)
        self.assertEqual(update_todo.call_args.kwargs["progress"], "/tmp/final.md")

    def test_only_scans_latest_assistant_message(self):
        # The earlier assistant message has a path; the latest does not -> no update.
        chat = _chat([
            _msg("assistant", "early /tmp/early.md"),
            _msg("user", "more"),
            _msg("assistant", "no path here"),
        ])
        with patch("storage.service.todo.update_todo") as update_todo:
            runner._hook_save_plan_to_todo(chat, {"todo_id": "9"}, user_id=1)
        update_todo.assert_not_called()

    def test_missing_todo_id_is_noop(self):
        chat = _chat([_msg("assistant", "/tmp/x.md")])
        with patch("storage.service.todo.update_todo") as update_todo:
            runner._hook_save_plan_to_todo(chat, {}, user_id=1)
        update_todo.assert_not_called()

    def test_no_path_in_assistant_message_is_noop(self):
        chat = _chat([_msg("assistant", "all done, nothing written")])
        with patch("storage.service.todo.update_todo") as update_todo:
            runner._hook_save_plan_to_todo(chat, {"todo_id": "9"}, user_id=1)
        update_todo.assert_not_called()


class RunPostHooksTest(unittest.TestCase):
    def test_dispatches_save_plan_to_todo(self):
        chat = _chat([])
        with patch.object(runner, "_hook_save_plan_to_todo") as hook:
            runner._run_post_hooks(chat, 123, [{"type": "save_plan_to_todo", "todo_id": "1"}])
        hook.assert_called_once_with(chat, {"type": "save_plan_to_todo", "todo_id": "1"}, 123)

    def test_unknown_hook_type_is_skipped(self):
        chat = _chat([])
        with patch.object(runner, "_hook_save_plan_to_todo") as hook:
            runner._run_post_hooks(chat, 123, [{"type": "mystery"}])
        hook.assert_not_called()

    def test_hook_exception_is_swallowed(self):
        chat = _chat([])
        with patch.object(runner, "_hook_save_plan_to_todo", side_effect=RuntimeError("boom")):
            # Must not raise — a failing hook should not crash the worker.
            runner._run_post_hooks(chat, 123, [{"type": "save_plan_to_todo"}])

    def test_empty_hooks_list_is_noop(self):
        with patch.object(runner, "_hook_save_plan_to_todo") as hook:
            runner._run_post_hooks(_chat([]), 123, [])
        hook.assert_not_called()


if __name__ == "__main__":
    unittest.main()
