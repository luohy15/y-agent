"""Tests for the plan-2662 steer-race safety net in worker.monitor._tail_and_process:

- sub-task 4: don't finalize a claude_code turn as done while a trailing user
  message exists that wasn't confirmed delivered; relaunch instead.
- sub-task 5: the plain claude_code completion path must merge
  prev_consumed + this turn's consumed_steer_ids before persisting, not
  overwrite (matching the codex/gemini/pi restart-with-steer paths).
"""

import unittest
from unittest.mock import AsyncMock, Mock, patch

from storage.dto.chat import Chat, Message
from worker.monitor import _tail_and_process


def _msg(role, msg_id, content="hi"):
    return Message(role=role, content=content, timestamp="", unix_timestamp=0, id=msg_id)


class SteerReconciliationTest(unittest.IsolatedAsyncioTestCase):
    def _chat(self, messages):
        return Chat(id="chat-1", create_time="", update_time="", messages=messages, work_dir="/repo")

    async def _run(self, chat, proc_overrides, result_overrides):
        proc = {
            "user_id": 1,
            "vm_name": "vm",
            "backend_type": "claude_code",
            "work_dir": "/repo",
            "initial_msg_count": 1,
            **proc_overrides,
        }
        result = {
            "offset": 10,
            "last_message_id": "m1",
            "session_id": "sess-1",
            "is_done": True,
            "result_data": None,
            "status": "completed",
            "consumed_steer_ids": [],
            **result_overrides,
        }

        with (
            patch("agent.config.resolve_vm_config", return_value=Mock()),
            patch("storage.service.chat.get_chat_by_id", new_callable=AsyncMock, return_value=chat),
            patch("storage.repository.chat.save_chat_by_id", new_callable=AsyncMock),
            patch("storage.repository.chat.set_chat_unread"),
            patch("agent.claude_code.tail_ssh_output", new_callable=AsyncMock, return_value=result),
            patch("worker.monitor.update_process_offset") as update_offset,
            patch("worker.monitor.complete_process") as complete_process,
            patch("worker.monitor.release_lease") as release_lease,
            patch("worker.monitor._relaunch_claude_code_turn", new_callable=AsyncMock) as relaunch,
        ):
            await _tail_and_process("chat-1", proc, "lambda-1", deadline_at=0)

        return update_offset, complete_process, release_lease, relaunch

    async def test_undelivered_trailing_message_triggers_relaunch_not_finalize(self):
        chat = self._chat([
            _msg("assistant", "m0", "initial reply"),
            _msg("user", "m1", "please also do X"),
        ])
        # m1 was never confirmed delivered (not in initial_msg_ids, not in consumed_steer_ids).
        update_offset, complete_process, release_lease, relaunch = await self._run(
            chat, {}, {"consumed_steer_ids": []},
        )

        relaunch.assert_awaited_once_with("chat-1", 1, {
            "user_id": 1, "vm_name": "vm", "backend_type": "claude_code",
            "work_dir": "/repo", "initial_msg_count": 1,
        }, backend="claude_code")
        complete_process.assert_called_once_with("chat-1", status="completed")
        self.assertFalse(chat.running)

    async def test_confirmed_delivered_trailing_message_finalizes_normally(self):
        chat = self._chat([
            _msg("assistant", "m0", "initial reply"),
            _msg("user", "m1", "please also do X"),
        ])
        # m1 was confirmed delivered this turn -> no reconciliation needed.
        update_offset, complete_process, release_lease, relaunch = await self._run(
            chat, {}, {"consumed_steer_ids": ["m1"]},
        )

        relaunch.assert_not_awaited()
        complete_process.assert_called_once_with("chat-1", status="completed")
        release_lease.assert_not_called()

    async def test_error_status_never_triggers_reconciliation(self):
        chat = self._chat([
            _msg("assistant", "m0", "initial reply"),
            _msg("user", "m1", "please also do X"),
        ])
        update_offset, complete_process, release_lease, relaunch = await self._run(
            chat, {}, {"status": "error", "consumed_steer_ids": []},
        )

        relaunch.assert_not_awaited()
        complete_process.assert_called_once_with("chat-1", status="error")

    async def test_no_trailing_user_message_finalizes_normally(self):
        chat = self._chat([
            _msg("user", "m0", "hi"),
            _msg("assistant", "m1", "done"),
        ])
        update_offset, complete_process, release_lease, relaunch = await self._run(
            chat, {}, {"consumed_steer_ids": []},
        )

        relaunch.assert_not_awaited()
        complete_process.assert_called_once_with("chat-1", status="completed")

    async def test_consumed_steer_ids_merge_with_prior_handoff(self):
        chat = self._chat([
            _msg("assistant", "m0", "initial reply"),
        ])
        update_offset, _, _, _ = await self._run(
            chat,
            {"consumed_steer_ids": ["prior-1"]},
            {"consumed_steer_ids": ["new-1"]},
        )

        self.assertEqual(
            sorted(update_offset.call_args.kwargs["consumed_steer_ids"]),
            ["new-1", "prior-1"],
        )


if __name__ == "__main__":
    unittest.main()
