import json
import re
import socket
import threading
import unittest
import asyncio

from agent.grok_build import GrokStreamConverter, _GrokUpdatesPoller, tail_grok_output


class _FakeChannel:
    def __init__(self, exit_status=0):
        self._exit_status = exit_status

    def close(self):
        pass

    def recv_exit_status(self):
        return self._exit_status

    def settimeout(self, timeout):
        pass


class _FakeStream:
    def __init__(self, lines, exit_status=0):
        self._lines = lines
        self.channel = _FakeChannel(exit_status)

    def __iter__(self):
        return iter(self._lines)

    def read(self):
        return "".join(self._lines).encode()


class _FakeSshClient:
    """Fake SSH client: streams `lines` for the tail command, reports the
    tmux session as dead for the liveness-check fallback (`_tmux_session_alive`)."""

    def __init__(self, lines):
        self._lines = lines

    def exec_command(self, cmd):
        if "has-session" in cmd:
            return None, _FakeStream(["dead\n"]), _FakeStream([])
        return None, _FakeStream(self._lines), _FakeStream([])


class _GrowingFileSshClient:
    """Fake SSH client honoring real `tail -c +N` (1-based) semantics against
    a growing file, so poller offset-tracking bugs (re-reading or skipping
    bytes) are caught the same way they would be against the genuine remote
    command. Also serves `echo $HOME` and the tmux liveness check used by the
    full `tail_grok_output` path."""

    def __init__(self, content: str = "", missing: bool = False, home: str = "/home/x"):
        self.content = content
        self.missing = missing
        self.home = home
        self.calls = 0
        self.requested_offsets = []

    def append(self, text: str) -> None:
        self.content += text

    def exec_command(self, cmd):
        self.calls += 1
        if "has-session" in cmd:
            return None, _FakeStream(["dead\n"]), _FakeStream([])
        if "echo $HOME" in cmd:
            return None, _FakeStream([self.home]), _FakeStream([])
        if self.missing:
            return None, _FakeStream([""], exit_status=1), _FakeStream(["No such file or directory\n"])
        m = re.search(r"tail -c \+(\d+)", cmd)
        if m:
            n = int(m.group(1))
            self.requested_offsets.append(n)
            data = self.content[n - 1:]
            return None, _FakeStream([data]), _FakeStream([])
        return None, _FakeStream([]), _FakeStream([])


_TIMEOUT = object()


class _TimeoutAwareStdoutStream:
    """Fake stdout channel stream: yields `items` in order; the `_TIMEOUT`
    sentinel raises `socket.timeout`, simulating an idle blocking read that
    has no new stdout line available yet (the only point at which
    `tail_grok_output` polls the updates.jsonl side channel)."""

    def __init__(self, items, exit_status=0):
        self._items = list(items)
        self.channel = _FakeChannel(exit_status)

    def __iter__(self):
        return self

    def __next__(self):
        if not self._items:
            raise StopIteration
        item = self._items.pop(0)
        if item is _TIMEOUT:
            raise socket.timeout()
        return item


class _RaceSshClient:
    """Fake SSH client for the stdout/updates ordering-race tests: the stdout
    stream is scripted (including timeout sentinels), while updates.jsonl
    honors real `tail -c +N` semantics against a growing buffer."""

    def __init__(self, stdout_items, updates_content="", home="/home/x"):
        self._stdout_items = stdout_items
        self.updates_content = updates_content
        self.home = home

    def exec_command(self, cmd):
        if "has-session" in cmd:
            return None, _FakeStream(["dead\n"]), _FakeStream([])
        if "echo $HOME" in cmd:
            return None, _FakeStream([self.home]), _FakeStream([])
        m = re.search(r"tail -c \+(\d+)", cmd)
        if m:
            n = int(m.group(1))
            data = self.updates_content[n - 1:]
            return None, _FakeStream([data]), _FakeStream([])
        return None, _TimeoutAwareStdoutStream(self._stdout_items), _FakeStream([])


def _tool_call_line(tool_call_id="tc-1", title="run_terminal_command", raw_input=None):
    return json.dumps({
        "timestamp": 1,
        "method": "session/update",
        "params": {
            "sessionId": "sess-1",
            "update": {
                "sessionUpdate": "tool_call",
                "toolCallId": tool_call_id,
                "title": title,
                "rawInput": raw_input or {"command": "echo hi"},
            },
        },
    })


def _tool_call_update_line(tool_call_id="tc-1", status="completed", text="hi\n"):
    return json.dumps({
        "timestamp": 2,
        "method": "session/update",
        "params": {
            "sessionId": "sess-1",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": tool_call_id,
                "status": status,
                "content": [{"content": {"type": "text", "text": text}}],
            },
        },
    })


class GrokStreamConverterTest(unittest.TestCase):
    def test_text_deltas_flush_as_single_assistant_message_on_end(self):
        converter = GrokStreamConverter()

        self.assertEqual(converter.process_line(json.dumps({"type": "text", "data": "Here's"})), [])
        self.assertEqual(converter.process_line(json.dumps({"type": "text", "data": " a summary"})), [])

        messages = converter.process_line(json.dumps({
            "type": "end",
            "stopReason": "EndTurn",
            "sessionId": "abc123",
            "requestId": "xyz789",
        }))

        self.assertEqual(converter.session_id, "abc123")
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].role, "assistant")
        self.assertEqual(messages[0].provider, "grok_build")
        self.assertEqual(messages[0].content, "Here's a summary")

    def test_thought_after_text_flushes_immediately_as_step_boundary(self):
        # Layer 1 (todo 2813): a thought run arriving after a text run started
        # marks an invisible tool-call boundary. Instead of buffering the
        # whole turn until `end`, the segment so far is flushed immediately
        # so reasoning/text appear step-by-step as the run progresses.
        converter = GrokStreamConverter()

        converter.process_line(json.dumps({"type": "text", "data": "I'll read the file."}))
        boundary_messages = converter.process_line(
            json.dumps({"type": "thought", "data": "The file contains a marker."})
        )

        self.assertEqual(len(boundary_messages), 1)
        self.assertEqual(boundary_messages[0].content, "I'll read the file.")
        self.assertIsNone(boundary_messages[0].reasoning_content)

        converter.process_line(json.dumps({"type": "text", "data": "`notes.txt` contains: X."}))
        final_messages = converter.process_line(json.dumps({"type": "end", "sessionId": "abc123"}))

        self.assertEqual(len(final_messages), 1)
        self.assertEqual(final_messages[0].content, "`notes.txt` contains: X.")
        self.assertEqual(final_messages[0].reasoning_content, "The file contains a marker.")
        # Causal chain: boundary message -> final message.
        self.assertEqual(final_messages[0].parent_id, boundary_messages[0].id)

    def test_thought_deltas_become_reasoning_content(self):
        converter = GrokStreamConverter()

        converter.process_line(json.dumps({"type": "thought", "data": "Analyzing the "}))
        converter.process_line(json.dumps({"type": "thought", "data": "directory structure..."}))
        converter.process_line(json.dumps({"type": "text", "data": "Done."}))

        messages = converter.process_line(json.dumps({
            "type": "end",
            "stopReason": "EndTurn",
            "sessionId": "abc123",
        }))

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "Done.")
        self.assertEqual(messages[0].reasoning_content, "Analyzing the directory structure...")

    def test_error_event_flushes_partial_text_and_logs(self):
        converter = GrokStreamConverter()

        converter.process_line(json.dumps({"type": "text", "data": "partial"}))
        messages = converter.process_line(json.dumps({
            "type": "error",
            "message": "Couldn't start session: boom",
        }))

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, "partial")

    def test_unknown_event_type_is_ignored_not_fatal(self):
        converter = GrokStreamConverter()
        messages = converter.process_line(json.dumps({"type": "tool_call", "name": "Bash"}))
        self.assertEqual(messages, [])

    def test_has_pending_reflects_buffered_segment(self):
        converter = GrokStreamConverter()
        self.assertFalse(converter.has_pending)
        converter.process_line(json.dumps({"type": "text", "data": "partial"}))
        self.assertTrue(converter.has_pending)
        converter.flush()
        self.assertFalse(converter.has_pending)

    def test_end_event_extracts_usage(self):
        converter = GrokStreamConverter()
        converter.process_line(json.dumps({"type": "text", "data": "done"}))
        converter.process_line(json.dumps({
            "type": "end",
            "sessionId": "abc123",
            "usage": {
                "input_tokens": 7210,
                "cache_read_input_tokens": 41000,
                "output_tokens": 1893,
                "reasoning_tokens": 412,
                "total_tokens": 50103,
            },
        }))
        self.assertEqual(converter.usage["input_tokens"], 7210)
        self.assertEqual(converter.usage["output_tokens"], 1893)

    def test_successful_run_via_tail(self):
        lines = [
            json.dumps({"type": "text", "data": "pong"}) + "\n",
            json.dumps({
                "type": "end",
                "stopReason": "EndTurn",
                "sessionId": "session-789",
                "requestId": "req-1",
            }) + "\n",
        ]

        result = asyncio.run(tail_grok_output(
            chat_id="chat-1",
            vm_config=None,
            ssh_client=_FakeSshClient(lines),
        ))

        self.assertTrue(result["is_done"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["session_id"], "session-789")
        self.assertEqual(result["updates_offset"], 0)

    def test_error_only_run_via_tail_is_error_status(self):
        lines = [
            json.dumps({
                "type": "error",
                "message": "Couldn't set model 'grok-4.5': Invalid params: \"unknown model id\".",
            }) + "\n",
        ]

        result = asyncio.run(tail_grok_output(
            chat_id="chat-1",
            vm_config=None,
            ssh_client=_FakeSshClient(lines),
        ))

        self.assertTrue(result["is_done"])
        self.assertEqual(result["status"], "error")
        self.assertIn("unknown model id", result["result_data"]["result"])

    def test_no_updates_poller_without_work_dir_or_session_id(self):
        # Layer 2 degrades to Layer 1 (stdout-only) when the caller doesn't
        # know the session id / work dir up front (e.g. legacy resume path).
        lines = [
            json.dumps({"type": "text", "data": "pong"}) + "\n",
            json.dumps({"type": "end", "sessionId": "session-789"}) + "\n",
        ]
        received = []

        result = asyncio.run(tail_grok_output(
            chat_id="chat-1",
            vm_config=None,
            ssh_client=_FakeSshClient(lines),
            message_callback=received.append,
        ))

        self.assertTrue(result["is_done"])
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].content, "pong")


class GrokUpdatesPollerTest(unittest.TestCase):
    def test_tool_call_flushes_pending_stdout_segment_first(self):
        converter = GrokStreamConverter()
        converter.process_line(json.dumps({"type": "text", "data": "I'll run a command."}))
        self.assertTrue(converter.has_pending)

        client = _GrowingFileSshClient()
        client.append(_tool_call_line() + "\n")
        received = []
        poller = _GrokUpdatesPoller(
            client, "/home/x/.grok/sessions/enc/sess-1/updates.jsonl",
            converter, threading.Lock(), received.append,
        )

        poller.poll_once()

        self.assertEqual(len(received), 2)
        self.assertEqual(received[0].content, "I'll run a command.")
        self.assertEqual(received[1].tool_calls[0]["function"]["name"], "Bash")
        self.assertEqual(
            json.loads(received[1].tool_calls[0]["function"]["arguments"]),
            {"command": "echo hi"},
        )
        # Ordering: the flushed stdout message is the tool call's parent.
        self.assertEqual(received[1].parent_id, received[0].id)
        self.assertFalse(converter.has_pending)

    def test_tool_call_update_completed_emits_tool_message_shaped_like_codex(self):
        converter = GrokStreamConverter()
        client = _GrowingFileSshClient()
        client.append(_tool_call_line() + "\n")
        received = []
        poller = _GrokUpdatesPoller(
            client, "/home/x/.grok/sessions/enc/sess-1/updates.jsonl",
            converter, threading.Lock(), received.append,
        )
        poller.poll_once()
        received.clear()

        client.append(_tool_call_update_line() + "\n")
        poller.poll_once()

        self.assertEqual(len(received), 1)
        msg = received[0]
        self.assertEqual(msg.role, "tool")
        self.assertEqual(msg.tool, "Bash")
        self.assertEqual(msg.arguments, {"command": "echo hi"})
        self.assertEqual(msg.tool_call_id, "tc-1")
        self.assertEqual(msg.content, "hi\n")

    def test_tool_call_update_in_progress_is_skipped(self):
        converter = GrokStreamConverter()
        client = _GrowingFileSshClient()
        client.append(_tool_call_update_line(status="in_progress") + "\n")
        received = []
        poller = _GrokUpdatesPoller(
            client, "/home/x/.grok/sessions/enc/sess-1/updates.jsonl",
            converter, threading.Lock(), received.append,
        )
        poller.poll_once()
        self.assertEqual(received, [])

    def test_dedupes_tool_call_already_seen(self):
        converter = GrokStreamConverter()
        client = _GrowingFileSshClient()
        client.append(_tool_call_line(tool_call_id="tc-old") + "\n")
        received = []
        poller = _GrokUpdatesPoller(
            client, "/home/x/.grok/sessions/enc/sess-1/updates.jsonl",
            converter, threading.Lock(), received.append,
            existing_tool_call_ids={"tc-old"},
        )
        poller.poll_once()
        self.assertEqual(received, [])

    def test_dedupes_completed_tool_result_already_seen(self):
        # Distinct from test_dedupes_tool_call_already_seen: a legacy replay
        # can carry the completed result independently of a re-seen call, so
        # the assistant-call dedupe set alone must not be relied on for it.
        converter = GrokStreamConverter()
        client = _GrowingFileSshClient()
        client.append(_tool_call_update_line(tool_call_id="tc-old") + "\n")
        received = []
        poller = _GrokUpdatesPoller(
            client, "/home/x/.grok/sessions/enc/sess-1/updates.jsonl",
            converter, threading.Lock(), received.append,
            existing_tool_result_ids={"tc-old"},
        )
        poller.poll_once()
        self.assertEqual(received, [])

    def test_full_legacy_call_and_completed_replay_emits_nothing(self):
        # Plan sub-task 5 / review finding 2: a proc registered before
        # updates_offset persistence shipped restarts the poll from byte 0 on
        # a Lambda handoff, re-delivering both halves of every prior tool
        # step. Both dedupe sets, seeded from chat history, must suppress it.
        converter = GrokStreamConverter()
        client = _GrowingFileSshClient()
        client.append(_tool_call_line(tool_call_id="tc-old") + "\n")
        client.append(_tool_call_update_line(tool_call_id="tc-old") + "\n")
        received = []
        poller = _GrokUpdatesPoller(
            client, "/home/x/.grok/sessions/enc/sess-1/updates.jsonl",
            converter, threading.Lock(), received.append,
            existing_tool_call_ids={"tc-old"},
            existing_tool_result_ids={"tc-old"},
        )
        poller.poll_once()
        self.assertEqual(received, [])

    def test_missing_updates_file_disables_after_max_attempts(self):
        converter = GrokStreamConverter()
        client = _GrowingFileSshClient(missing=True)
        received = []
        poller = _GrokUpdatesPoller(
            client, "/home/x/.grok/sessions/enc/sess-1/updates.jsonl",
            converter, threading.Lock(), received.append,
        )

        for _ in range(10):
            poller.poll_once()

        self.assertFalse(poller._available)
        # No more SSH calls once disabled.
        calls_when_disabled = client.calls
        poller.poll_once()
        self.assertEqual(client.calls, calls_when_disabled)

    def test_growing_file_partial_line_is_not_duplicated_or_lost(self):
        # Review finding 1: a real `tail -c +N` never re-delivers bytes
        # already read. The fake here honors that contract (unlike the old,
        # removed test that reset `offset` to 0 between polls), so a bug that
        # re-reads (and thus duplicates/corrupts) the buffered partial line
        # would make this test fail by losing the tool call.
        converter = GrokStreamConverter()
        full_line = _tool_call_line()
        client = _GrowingFileSshClient()
        client.append(full_line[:20])  # mid-write: only part of the line landed
        received = []
        poller = _GrokUpdatesPoller(
            client, "/home/x/.grok/sessions/enc/sess-1/updates.jsonl",
            converter, threading.Lock(), received.append,
        )

        poller.poll_once()
        self.assertEqual(received, [])
        self.assertEqual(poller._buf, full_line[:20])
        self.assertEqual(poller.offset, 0)  # no complete line yet: logical offset unchanged
        self.assertEqual(client.requested_offsets, [1])

        # The rest of the line (plus a newline and the start of the next
        # write) lands.
        client.append(full_line[20:] + "\n")
        poller.poll_once()

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].tool_calls[0]["function"]["name"], "Bash")
        self.assertEqual(poller.offset, len(full_line) + 1)
        # The second read started exactly where the first left off (byte 21,
        # i.e. `tail -c +21`), never re-requesting the already-read prefix.
        self.assertEqual(client.requested_offsets, [1, 21])

    def test_growing_file_across_many_small_writes(self):
        # Same contract as above, exercised over several small appends
        # (a slower, more realistic growth pattern) across two tool steps.
        converter = GrokStreamConverter()
        client = _GrowingFileSshClient()
        received = []
        poller = _GrokUpdatesPoller(
            client, "/home/x/.grok/sessions/enc/sess-1/updates.jsonl",
            converter, threading.Lock(), received.append,
        )

        full = _tool_call_line() + "\n" + _tool_call_update_line() + "\n"
        chunk_size = 7
        for i in range(0, len(full), chunk_size):
            client.append(full[i:i + chunk_size])
            poller.poll_once()

        self.assertEqual(len(received), 2)
        self.assertEqual(received[0].tool_calls[0]["function"]["name"], "Bash")
        self.assertEqual(received[1].role, "tool")
        self.assertEqual(poller.offset, len(full))
        # Every read continued exactly from the end of the previous one.
        self.assertEqual(
            client.requested_offsets,
            [1] + [len(full[:i]) + 1 for i in range(chunk_size, len(full), chunk_size)],
        )


class GrokTailOrderingRaceTest(unittest.TestCase):
    """Integration-level tests driving the full `tail_grok_output` interleave:
    the stdout reader and the updates.jsonl poller are two independently
    "scheduled" sources, and these assert source order survives regardless of
    which one would otherwise have data ready first."""

    def test_updates_reader_winning_race_does_not_reorder_stdout_text(self):
        # Review finding 3: updates.jsonl already has a tool_call available
        # from the very first possible read (simulating it "winning" if
        # polled independently before stdout is drained). The interleave
        # must still flush/emit the earlier stdout text before the tool call.
        text_line = json.dumps({"type": "text", "data": "I'll run a command."}) + "\n"
        end_line = json.dumps({"type": "end", "sessionId": "sess-1"}) + "\n"

        client = _RaceSshClient(
            stdout_items=[text_line, _TIMEOUT, end_line],
            updates_content=_tool_call_line() + "\n",
        )
        received = []

        result = asyncio.run(tail_grok_output(
            chat_id="chat-1",
            vm_config=None,
            ssh_client=client,
            message_callback=received.append,
            work_dir="/repo",
            session_id="sess-1",
        ))

        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(received), 2)
        self.assertEqual(received[0].content, "I'll run a command.")
        self.assertIsNotNone(received[1].tool_calls)
        self.assertEqual(received[1].parent_id, received[0].id)

    def test_continuous_stdout_reconciles_tool_call_between_lines(self):
        # Review finding (round 2): timeout-only reconciliation is
        # insufficient. If stdout stays continuously readable (no idle gap
        # ever occurs) while updates.jsonl already has the intervening
        # tool_call (and its completed result), the side channel must still
        # be reconciled between the pre-tool and post-tool stdout lines --
        # not only when the read times out -- or persisted order/parent
        # chaining come out as text -> text -> tool call instead of
        # text -> tool call -> result -> text.
        before_line = json.dumps({"type": "text", "data": "Before tool."}) + "\n"
        thought_line = json.dumps({"type": "thought", "data": "Deciding what to run."}) + "\n"
        after_line = json.dumps({"type": "text", "data": "After tool."}) + "\n"
        end_line = json.dumps({"type": "end", "sessionId": "sess-1"}) + "\n"

        client = _RaceSshClient(
            # No _TIMEOUT sentinel anywhere: stdout is continuously readable.
            stdout_items=[before_line, thought_line, after_line, end_line],
            updates_content=_tool_call_line() + "\n" + _tool_call_update_line() + "\n",
        )
        received = []

        result = asyncio.run(tail_grok_output(
            chat_id="chat-1",
            vm_config=None,
            ssh_client=client,
            message_callback=received.append,
            work_dir="/repo",
            session_id="sess-1",
        ))

        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(received), 4)

        pre_tool, tool_call_msg, tool_result_msg, post_tool = received

        self.assertEqual(pre_tool.role, "assistant")
        self.assertEqual(pre_tool.content, "Before tool.")
        self.assertIsNone(pre_tool.tool_calls)

        self.assertIsNotNone(tool_call_msg.tool_calls)
        self.assertEqual(tool_call_msg.tool_calls[0]["function"]["name"], "Bash")

        self.assertEqual(tool_result_msg.role, "tool")
        self.assertEqual(tool_result_msg.tool_call_id, "tc-1")

        self.assertEqual(post_tool.role, "assistant")
        self.assertEqual(post_tool.content, "After tool.")
        self.assertEqual(post_tool.reasoning_content, "Deciding what to run.")

        # Causal chain must match the persisted order exactly.
        self.assertEqual(tool_call_msg.parent_id, pre_tool.id)
        self.assertEqual(tool_result_msg.parent_id, tool_call_msg.id)
        self.assertEqual(post_tool.parent_id, tool_result_msg.id)

    def test_deadline_after_poller_flush_advances_safe_offset(self):
        # Review finding 4: when the side-channel poll flushes a pending
        # stdout segment, the stdout high-water mark must advance too, so a
        # Lambda deadline/resume right after that flush neither loses nor
        # re-emits (duplicates) the already-persisted text.
        text_line = json.dumps({"type": "text", "data": "I'll run a command."}) + "\n"

        deadline_calls = {"n": 0}

        def check_deadline():
            deadline_calls["n"] += 1
            # False while the single stdout line is processed, True once we
            # reach the timeout branch (right after the poller has run).
            return deadline_calls["n"] > 1

        client = _RaceSshClient(
            stdout_items=[text_line, _TIMEOUT],
            updates_content=_tool_call_line() + "\n",
        )
        received = []

        result = asyncio.run(tail_grok_output(
            chat_id="chat-1",
            vm_config=None,
            ssh_client=client,
            message_callback=received.append,
            check_deadline_fn=check_deadline,
            work_dir="/repo",
            session_id="sess-1",
        ))

        self.assertEqual(result["status"], "monitoring")
        self.assertFalse(result["is_done"])
        # The flushed text (line 1) is already persisted, so the safe offset
        # must have advanced past it rather than staying at 0.
        self.assertEqual(result["offset"], 1)
        self.assertEqual(len(received), 2)
        self.assertEqual(received[0].content, "I'll run a command.")
        self.assertIsNotNone(received[1].tool_calls)


if __name__ == "__main__":
    unittest.main()
