"""Resume-handle lifecycle for claude_code turns (todo 2930 follow-up).

Two halves of the same invariant:
  * a chat with no `external_id` launches a fresh session (no `-r`) — the state
    every chat migrated off codex/grok_build/gemini_cli/pi_cli must be in;
  * the handle is dropped when, and only when, Claude Code affirmatively refused
    it (`resume_refused`, from the refusal message in the CLI's own error result
    event, or from this run's stderr on the no-result branch). Every other failed
    turn keeps it: the death-report text alone cannot tell a refused handle from a
    launcher that never started the CLI, an external kill, or a CLI-level outage
    that would otherwise wipe the whole fleet's handles at once.
"""

import unittest
from unittest.mock import patch

from storage.entity.dto import BotConfig, Chat, Message, VmConfig
from storage.util import get_unix_timestamp, get_utc_iso8601_timestamp
from worker.monitor import _apply_completion_metadata
from worker.runner import _build_claude_code_params

WORK_DIR = "/repo"

# The exact `result_data["result"]` strings agent/claude_code.py produces for a
# turn that ended without a final result event, plus the launcher's synthetic
# work_dir failure. Only the first carries the affirmative refusal signal.
REFUSED = (
    "Claude Code refused the recorded session id (no conversation found with it "
    "under this work dir). The session handle is dropped, so the next turn starts "
    "a fresh session."
)
EXIT_CODE_1 = (
    "Claude Code exited before producing output: process exited with code 1 "
    "— likely a startup or resume error."
)
EXIT_CODE_127 = (
    "Claude Code exited before producing output: process exited with code 127 "
    "— likely a startup or resume error."
)
SIGTERM = (
    "Claude Code exited before producing output: terminated by SIGTERM (15) "
    "— likely killed by an external reaper/OOM, not a resume failure."
)
SIGKILL = (
    "Claude Code exited before producing output: terminated by SIGKILL (9) "
    "— likely killed by an external reaper/OOM, not a resume failure."
)
EXIT_UNREADABLE = (
    "Claude Code exited before producing output: exit status unreadable "
    "(ssh error: RuntimeError: SSH command failed (exit 1): )."
)
GENERIC = (
    "Claude Code exited before producing output — likely a session resume failure "
    "or startup error."
)
WORK_DIR_MISSING = f"work_dir not found: {WORK_DIR}"


def _chat(external_id=None, work_dir=WORK_DIR) -> Chat:
    return Chat(
        id="chat-1",
        create_time=get_utc_iso8601_timestamp(),
        update_time=get_utc_iso8601_timestamp(),
        messages=[
            Message(
                role="user",
                content="hello",
                timestamp=get_utc_iso8601_timestamp(),
                unix_timestamp=get_unix_timestamp(),
                id="m1",
            )
        ],
        external_id=external_id,
        work_dir=work_dir,
    )


def _params(chat: Chat) -> dict:
    vm = VmConfig(name="vm", vm_name="user@example.com", api_token="key", work_dir=WORK_DIR)
    with patch("worker.runner.agent_config.resolve_vm_config", return_value=vm):
        return _build_claude_code_params(
            chat, "chat-1", 1, BotConfig(name="claude_code", backend="claude_code"),
        )


class MigratedChatLaunchesFreshTest(unittest.TestCase):
    def test_no_external_id_launches_without_resume(self):
        params = _params(_chat(external_id=None))
        self.assertFalse(params["resume"])
        self.assertIsNone(params["session_id"])
        self.assertNotIn("-r", params["cmd"])

    def test_external_id_still_resumes_when_work_dir_matches(self):
        params = _params(_chat(external_id="session-a"))
        self.assertTrue(params["resume"])
        self.assertEqual(params["cmd"][params["cmd"].index("-r") + 1], "session-a")


class RefusedHandleTest(unittest.IsolatedAsyncioTestCase):
    async def _apply(self, chat, status="error", error_text=EXIT_CODE_1, resume_refused=False,
                     run_session_id=None, launch_session_id=None, run_work_dir=WORK_DIR):
        await _apply_completion_metadata(
            fresh=chat,
            result={"status": status, "session_id": run_session_id, "resume_refused": resume_refused},
            result_data={"is_error": True, "result": error_text} if status == "error" else {},
            proc={"work_dir": run_work_dir, "session_id": launch_session_id},
            chat_id="chat-1",
        )

    async def test_refusal_drops_the_handle(self):
        chat = _chat(external_id="codex-thread-uuid")
        await self._apply(chat, error_text=REFUSED, resume_refused=True)
        self.assertIsNone(chat.external_id)
        self.assertEqual(chat.messages[-1].content, REFUSED)

    async def test_every_other_failure_shape_keeps_the_handle(self):
        """The regression this narrowing exists for: the death-report text is not
        evidence about the handle.

        `work_dir not found` never launches the CLI (detach.py writes a synthetic
        result and returns), SIGTERM/SIGKILL can leave a live session, an
        unreadable exit status is unknowable, and exit 1 / 127 also cover a
        missing binary, bad credentials or a bad `--model` — failures that are
        correlated across chats, so healing on them would drop the handle of
        every chat taking a turn during an unrelated CLI outage.
        """
        for label, error_text in (
            ("work_dir not found", WORK_DIR_MISSING),
            ("exit 1 (startup or resume, unknown which)", EXIT_CODE_1),
            ("exit 127 (missing/broken claude binary)", EXIT_CODE_127),
            ("SIGTERM before the system event", SIGTERM),
            ("SIGKILL before the system event", SIGKILL),
            ("exit status unreadable", EXIT_UNREADABLE),
            ("generic no-result death report", GENERIC),
        ):
            with self.subTest(shape=label):
                chat = _chat(external_id="session-a")
                await self._apply(chat, error_text=error_text)
                self.assertEqual(chat.external_id, "session-a")

    async def test_refusal_without_the_flag_keeps_the_handle(self):
        """Fail-safe direction: if the stderr probe could not run (SSH error), the
        text alone must not trigger the heal."""
        chat = _chat(external_id="session-a")
        await self._apply(chat, error_text=REFUSED, resume_refused=False)
        self.assertEqual(chat.external_id, "session-a")

    async def test_refusal_does_not_re_persist_the_refused_id(self):
        """The observed production failure. A refusal's result event echoes the
        refused id back as its own `session_id`, so if clearing did not come
        first the dead handle would be written straight back and the chat would
        stay wedged forever — which is exactly what chat 9e932e did."""
        chat = _chat(external_id="bogus-uuid")
        await self._apply(chat, error_text=REFUSED, resume_refused=True,
                          run_session_id="bogus-uuid")
        self.assertIsNone(chat.external_id)

    async def test_refusal_with_mismatched_work_dir_keeps_the_handle(self):
        """Mirrors the existing cwd guard: a run whose cwd differs from the
        chat's says nothing about the handle recorded for that work_dir."""
        chat = _chat(external_id="session-a")
        await self._apply(chat, error_text=REFUSED, resume_refused=True, run_work_dir="/other")
        self.assertEqual(chat.external_id, "session-a")

    async def test_error_that_reported_a_session_keeps_it(self):
        chat = _chat(external_id="session-a")
        await self._apply(chat, run_session_id="session-a")
        self.assertEqual(chat.external_id, "session-a")

    async def test_successful_turn_persists_the_new_session(self):
        chat = _chat(external_id=None)
        await self._apply(chat, status="completed", run_session_id="session-new")
        self.assertEqual(chat.external_id, "session-new")

    async def test_refusal_without_a_handle_is_a_noop(self):
        chat = _chat(external_id=None)
        await self._apply(chat, error_text=REFUSED, resume_refused=True)
        self.assertIsNone(chat.external_id)

    async def test_refusal_never_persists_after_an_out_of_band_clear(self):
        """The clearing gate needs a handle to clear, so a handle cleared out of
        band (migration SQL, twice in todo 2930's own trace) while a refused turn
        was in flight used to fall through to the persist branch and resurrect the
        echoed dead id into the column that was just cleaned. A refusal must never
        write a handle, whatever the column currently holds."""
        chat = _chat(external_id=None)
        await self._apply(chat, error_text=REFUSED, resume_refused=True,
                          run_session_id="bogus-uuid")
        self.assertIsNone(chat.external_id)

    async def test_refusal_with_mismatched_work_dir_persists_nothing_either(self):
        """Same rule under the cwd guard: no clear (the run says nothing about the
        handle recorded for another work_dir) and no write."""
        chat = _chat(external_id="session-a")
        await self._apply(chat, error_text=REFUSED, resume_refused=True,
                          run_session_id="bogus-uuid", run_work_dir="/other")
        self.assertEqual(chat.external_id, "session-a")


if __name__ == "__main__":
    unittest.main()
