"""Regression tests for the `_ssh_exec` paramiko deadlock (todo 2885).

`_ssh_exec` used to call `recv_exit_status()` before reading stdout. The remote
command cannot exit until it has written all of its output, and it blocks once
it fills paramiko's channel window (~2 MiB) when nothing drains the channel, so
any larger output hung both sides forever. The fakes below stand in for that
window: `recv_exit_status()` refuses to report an exit code until the payload
has actually been read.
"""

import socket
import threading
import unittest
from unittest.mock import Mock

from agent.claude_code import _claude_image_block, _ssh_exec
from agent.grok_build import _UPDATES_MAX_MISSING_POLLS, GrokStreamConverter, _GrokUpdatesPoller

# Larger than paramiko's default channel window (64 * 2**15 = 2,097,152 bytes),
# i.e. the size at which the old read order deadlocked.
WINDOW_BUSTING_SIZE = 2_500_000


class _FakeChannel:
    """Channel whose exit status is only available once stdout was drained."""

    def __init__(self, streams, exit_code: int):
        self._streams = streams
        self._exit_code = exit_code

    def recv_exit_status(self) -> int:
        if not self._streams.stdout_read:
            # The real thing blocks forever here; fail loudly instead.
            raise AssertionError("recv_exit_status() called before stdout was drained")
        self._streams.calls.append("recv_exit_status")
        return self._exit_code


class _FakeStream:
    def __init__(self, payload: bytes, streams, name: str):
        self._payload = payload
        self._streams = streams
        self._name = name
        self.channel = streams.channel

    def read(self) -> bytes:
        self._streams.calls.append(f"read:{self._name}")
        if self._name == "stdout":
            self._streams.stdout_read = True
        return self._payload


class _FakeStreams:
    """stdin/stdout/stderr triple with the window behaviour above."""

    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", exit_code: int = 0):
        self.calls = []
        self.stdout_read = False
        self.channel = _FakeChannel(self, exit_code)
        self.stdout = _FakeStream(stdout, self, "stdout")
        self.stderr = _FakeStream(stderr, self, "stderr")

    def as_triple(self):
        return Mock(), self.stdout, self.stderr


def _client_for(streams: _FakeStreams, exec_calls: list = None):
    client = Mock()

    def _exec_command(cmd, **kwargs):
        if exec_calls is not None:
            exec_calls.append((cmd, kwargs))
        return streams.as_triple()

    client.exec_command.side_effect = _exec_command
    return client


class SshExecDrainOrderTest(unittest.TestCase):
    def test_drains_stdout_before_waiting_for_exit_status(self):
        payload = b"x" * WINDOW_BUSTING_SIZE
        streams = _FakeStreams(stdout=payload)

        output = _ssh_exec(_client_for(streams), "cat big-file")

        self.assertEqual(len(output), WINDOW_BUSTING_SIZE)
        self.assertEqual(streams.calls[0], "read:stdout")
        self.assertEqual(streams.calls[-1], "recv_exit_status")

    def test_passes_a_read_timeout_to_exec_command(self):
        exec_calls = []
        streams = _FakeStreams(stdout=b"ok\n")

        _ssh_exec(_client_for(streams, exec_calls), "echo ok")

        self.assertEqual(len(exec_calls), 1)
        timeout = exec_calls[0][1].get("timeout")
        self.assertIsNotNone(timeout, "exec_command must carry a timeout")
        self.assertGreater(timeout, 0)

    def test_non_zero_exit_raises_with_stderr(self):
        streams = _FakeStreams(stdout=b"", stderr=b"boom", exit_code=1)

        with self.assertRaises(RuntimeError) as ctx:
            _ssh_exec(_client_for(streams), "false")

        self.assertIn("boom", str(ctx.exception))

    def test_non_zero_exit_tolerated_for_missing_tmux_session(self):
        for stderr in (b"no server running on /tmp/tmux-1000/default", b"session not found: cc-x"):
            with self.subTest(stderr=stderr):
                streams = _FakeStreams(stdout=b"partial\n", stderr=stderr, exit_code=1)

                self.assertEqual(_ssh_exec(_client_for(streams), "tmux has-session"), "partial\n")

    def test_read_timeout_propagates(self):
        client = Mock()
        client.exec_command.side_effect = socket.timeout("timed out")

        with self.assertRaises(socket.timeout):
            _ssh_exec(client, "cat stalled-file")


class SshExecCallSiteTest(unittest.TestCase):
    """The two call sites that can legitimately exceed the channel window."""

    def test_grok_updates_poller_reads_an_oversized_chunk(self):
        line = '{"params":{"update":{"sessionUpdate":"other"}}}'
        padding = "\n".join([line] * (WINDOW_BUSTING_SIZE // (len(line) + 1)))
        streams = _FakeStreams(stdout=(padding + "\n").encode())
        poller = _GrokUpdatesPoller(
            client=_client_for(streams),
            updates_path="/home/roy/.grok/sessions/s/updates.jsonl",
            converter=GrokStreamConverter(),
            lock=threading.RLock(),
            message_callback=lambda msg: None,
        )

        poller.poll_once()

        self.assertEqual(poller.offset, len(padding) + 1)
        self.assertTrue(poller._available)

    def test_claude_image_block_reads_an_oversized_base64_payload(self):
        streams = _FakeStreams(stdout=b"A" * WINDOW_BUSTING_SIZE + b"\n")

        block = _claude_image_block("/Users/roy/luohy15/assets/images/vm-only.png",
                                    client=_client_for(streams))

        self.assertEqual(block["source"]["media_type"], "image/png")
        self.assertEqual(len(block["source"]["data"]), WINDOW_BUSTING_SIZE)


class GrokUpdatesPollerTimeoutTest(unittest.TestCase):
    """A stalled read must degrade to a missed poll, not kill the tail loop."""

    def _timing_out_poller(self):
        client = Mock()
        client.exec_command.side_effect = socket.timeout("timed out")
        return _GrokUpdatesPoller(
            client=client,
            updates_path="/home/roy/.grok/sessions/s/updates.jsonl",
            converter=GrokStreamConverter(),
            lock=threading.RLock(),
            message_callback=lambda msg: None,
            offset=42,
        )

    def test_timeout_counts_as_a_missed_poll(self):
        poller = self._timing_out_poller()

        poller.poll_once()  # must not raise

        self.assertEqual(poller._missing_polls, 1)
        self.assertEqual(poller.offset, 42)
        self.assertTrue(poller._available)

    def test_repeated_timeouts_disable_the_side_channel(self):
        poller = self._timing_out_poller()

        for _ in range(_UPDATES_MAX_MISSING_POLLS):
            poller.poll_once()

        self.assertFalse(poller._available)


if __name__ == "__main__":
    unittest.main()
