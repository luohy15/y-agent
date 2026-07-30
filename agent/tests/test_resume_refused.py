"""Affirmative detection of a refused resume handle (todo 2930 follow-up).

The worker clears `chat.external_id` only when Claude Code itself named the
handle as the cause, so these probes are the single source of that decision. What
matters here is that they report True *only* on the CLI's own refusal message and
fail safe (False) in every other situation, including when they cannot run.

`RefusalTakesTheResultEventBranchTest` additionally pins *which* branch a real
refusal takes. The first cut of this heal wired detection into the no-result
branch only, where a refusal never lands, so it could not fire at all — every
unit test passed and production stayed wedged.
"""

import json
import unittest
from unittest.mock import Mock

from agent.claude_code import (
    RESUME_REFUSED_MARKER,
    _result_event_resume_refused,
    tail_ssh_output,
)

# Captured verbatim from `claude -p --output-format stream-json --verbose -r
# <unknown-uuid> ...` on the VM (Claude Code 2.1.219), run under a cwd that has
# other sessions. This is the whole reproduction in one line: stdout DOES get a
# final result event, so `tail_ssh_output` takes its result branch and never
# reaches the no-result stderr probe.
REAL_REFUSAL_STDOUT_LINE = (
    '{"type":"result","subtype":"error_during_execution","duration_ms":0,'
    '"duration_api_ms":0,"is_error":true,"num_turns":0,"stop_reason":null,'
    '"session_id":"67955d71-44a2-4c62-b0b7-64d13f397af1","total_cost_usd":0,'
    '"usage":{"input_tokens":0,"cache_creation_input_tokens":0,'
    '"cache_read_input_tokens":0,"output_tokens":0,"server_tool_use":'
    '{"web_search_requests":0,"web_fetch_requests":0},"service_tier":"standard",'
    '"cache_creation":{"ephemeral_1h_input_tokens":0,'
    '"ephemeral_5m_input_tokens":0},"inference_geo":"","iterations":[],'
    '"speed":"standard"},"modelUsage":{},"permission_denials":[],'
    '"uuid":"87958fb0-1241-4855-bf67-2a025d6e1e51","errors":'
    '["No conversation found with session ID: '
    '67955d71-44a2-4c62-b0b7-64d13f397af1"]}'
)
REFUSED_SESSION_ID = "67955d71-44a2-4c62-b0b7-64d13f397af1"


class EmptyChannel:
    """A tail channel that yields no lines and closes immediately: the process
    is already gone and never wrote a result event."""

    def __init__(self):
        self.channel = self

    def __iter__(self):
        return iter([])

    def close(self):
        pass


class OneLineThenClose:
    def __init__(self, line: str):
        self._line = line
        self._served = False
        self.channel = self

    def __iter__(self):
        return self

    def __next__(self):
        if self._served:
            raise StopIteration
        self._served = True
        return self._line

    def close(self):
        pass


def _ssh_ok(text: str = "") -> tuple:
    stdout = Mock()
    stdout.channel.recv_exit_status.return_value = 0
    stdout.read.return_value = text.encode()
    stderr = Mock()
    stderr.read.return_value = b""
    return (Mock(), stdout, stderr)


def _ssh_fail(err: str = "boom") -> tuple:
    stdout = Mock()
    stdout.channel.recv_exit_status.return_value = 1
    stdout.read.return_value = b""
    stderr = Mock()
    stderr.read.return_value = err.encode()
    return (Mock(), stdout, stderr)


def _make_client(tail_channel, *, stderr_text: str = "", exit_code: str = "1",
                 stderr_readable: bool = True):
    """Mock SSH client for the no-result branch: routes the sentinel check, the
    tmux liveness check, the stderr probe and the exit-code read by substring."""
    calls = []

    def exec_command(cmd, *args, **kwargs):
        calls.append(cmd)
        if "wait $TAIL_PID" in cmd:
            return (Mock(), tail_channel, Mock())
        if "killed" in cmd:
            return _ssh_ok("")
        if "has-session" in cmd:
            return _ssh_ok("dead\n")
        if ".stderr" in cmd:
            return _ssh_ok(stderr_text) if stderr_readable else _ssh_fail()
        if cmd.strip().startswith("cat "):
            return _ssh_ok(exit_code)
        return _ssh_ok("")

    client = Mock()
    client.exec_command.side_effect = exec_command
    return client, calls


async def _tail(client):
    return await tail_ssh_output(
        chat_id="chat-1",
        vm_config=Mock(),
        offset=0,
        message_callback=lambda msg: None,
        ssh_client=client,
    )


class ResumeRefusedProbeTest(unittest.IsolatedAsyncioTestCase):
    async def test_stderr_refusal_sets_the_flag_and_names_the_cause(self):
        client, calls = _make_client(
            EmptyChannel(),
            stderr_text=f"{RESUME_REFUSED_MARKER}: 0b3c4d5e-1111-2222-3333-444455556666\n",
        )
        result = await _tail(client)

        self.assertEqual(result["status"], "error")
        self.assertTrue(result["resume_refused"])
        self.assertIn("refused the recorded session id", result["result_data"]["result"])
        self.assertTrue(any(".stderr" in c for c in calls))

    async def test_unrelated_startup_stderr_does_not_set_the_flag(self):
        """A missing or mid-upgrade binary, or a node OOM, dies before writing any
        result event and lands here. Nothing it says is about the handle.

        Which branch a failure takes is not a taxonomy to lean on: a bad `--model`
        looks like this on stderr but *does* emit an error result event (probed
        live on 2.1.219), so it is covered by
        `RefusalTakesTheResultEventBranchTest` instead. Only the marker separates
        a refusal from any of them.
        """
        client, _ = _make_client(
            EmptyChannel(),
            stderr_text="node: bad option: --effort\n",
            exit_code="127",
        )
        result = await _tail(client)

        self.assertEqual(result["status"], "error")
        self.assertFalse(result["resume_refused"])
        self.assertIn("process exited with code 127", result["result_data"]["result"])

    async def test_empty_stderr_does_not_set_the_flag(self):
        client, _ = _make_client(EmptyChannel(), stderr_text="")
        result = await _tail(client)
        self.assertFalse(result["resume_refused"])

    async def test_unreadable_stderr_fails_safe(self):
        """If the probe cannot run, report no refusal: a missed refusal costs one
        wedged turn, a false one costs a live session."""
        client, _ = _make_client(EmptyChannel(), stderr_readable=False)
        result = await _tail(client)
        self.assertFalse(result["resume_refused"])

    async def test_launcher_work_dir_failure_never_probes_stderr(self):
        """`work_dir not found` is a synthetic result event written to stdout by
        the launcher before tmux starts, so it never enters the no-result branch
        and can never be mistaken for a refusal."""
        line = json.dumps({
            "type": "result", "is_error": True, "result": "work_dir not found: /repo",
        }) + "\n"
        client, calls = _make_client(OneLineThenClose(line))
        result = await _tail(client)

        self.assertEqual(result["status"], "error")
        self.assertFalse(result["resume_refused"])
        self.assertFalse(any(".stderr" in c for c in calls))


class RefusalTakesTheResultEventBranchTest(unittest.IsolatedAsyncioTestCase):
    """Pin the branch, not just the marker.

    The regression these exist for: detection that only lives on the no-result
    branch is dead code, because a refused resume emits an error *result* event.
    Every assertion below is derived from `REAL_REFUSAL_STDOUT_LINE`, captured
    from the CLI itself, so moving detection back off the result branch fails
    here instead of silently in production.
    """

    def test_captured_refusal_is_an_error_result_event_with_no_result_text(self):
        """The shape that decides the branch, asserted on the captured bytes."""
        obj = json.loads(REAL_REFUSAL_STDOUT_LINE)

        # A result event: `tail_ssh_output` stores it and returns, so no
        # no-result handling (and no stderr probe) ever runs for this turn.
        self.assertEqual(obj["type"], "result")
        self.assertTrue(obj["is_error"])
        # The marker lives in the structured `errors` list...
        self.assertTrue(any(RESUME_REFUSED_MARKER in e for e in obj["errors"]))
        # ...and there is no `result` text, which is why the worker's fallback
        # rendered the useless "Claude Code exited with an error." the wedged
        # chats showed.
        self.assertNotIn("result", obj)
        # The event echoes the refused id back as its own session_id, so the
        # worker must clear before it considers persisting (see
        # worker/tests/test_external_id_resume.py).
        self.assertEqual(obj["session_id"], REFUSED_SESSION_ID)

    async def test_captured_refusal_flags_without_consulting_stderr(self):
        client, calls = _make_client(OneLineThenClose(REAL_REFUSAL_STDOUT_LINE + "\n"))
        result = await _tail(client)

        self.assertEqual(result["status"], "error")
        self.assertTrue(result["resume_refused"])
        # Detected from the result event alone: no stderr read, no exit-code read.
        self.assertFalse(any(".stderr" in c for c in calls))
        self.assertEqual(result["session_id"], REFUSED_SESSION_ID)

    async def test_captured_refusal_names_the_cause_for_the_user(self):
        client, _ = _make_client(OneLineThenClose(REAL_REFUSAL_STDOUT_LINE + "\n"))
        result = await _tail(client)

        text = result["result_data"]["result"]
        self.assertIn("refused the recorded session id", text)
        self.assertIn("next turn starts a fresh session", text)

    def test_unrelated_error_result_event_does_not_flag(self):
        """An error result event is not evidence about the handle: an API outage,
        a bad --model or a mid-turn crash all land on this same branch. The
        `errors: null` case is the shape a bad `--model` actually produces
        (probed live on 2.1.219), which is why the branch alone proves nothing."""
        for label, event in (
            ("api failure", {"errors": ["API Error: 500 Internal Server Error"]}),
            ("bad --model (errors: null)", {"errors": None}),
            ("no errors key", {}),
            ("errors not a list", {"errors": RESUME_REFUSED_MARKER + ": x"}),
            ("empty errors", {"errors": []}),
        ):
            with self.subTest(shape=label):
                self.assertFalse(_result_event_resume_refused(
                    {"type": "result", "is_error": True, "result": "boom", **event}
                ))

    def test_marker_in_model_authored_result_text_does_not_flag(self):
        """Read `errors` only. `result` carries the model's own final text, and a
        chat debugging this very feature would quote the marker verbatim."""
        event = {
            "type": "result",
            "is_error": True,
            "result": f"I reproduced it: the CLI printed '{RESUME_REFUSED_MARKER}: abc'.",
        }
        self.assertFalse(_result_event_resume_refused(event))

    def test_successful_run_mentioning_the_marker_does_not_flag(self):
        """A run that recovered reports a usable session id; that id must be
        persisted, not dropped."""
        event = {
            "type": "result",
            "is_error": False,
            "session_id": "fresh-session",
            "errors": [f"{RESUME_REFUSED_MARKER}: stale-id"],
        }
        self.assertFalse(_result_event_resume_refused(event))

    def test_reworded_marker_fails_safe(self):
        event = {
            "type": "result", "is_error": True,
            "errors": ["Session not found: 67955d71"],
        }
        self.assertFalse(_result_event_resume_refused(event))


if __name__ == "__main__":
    unittest.main()
