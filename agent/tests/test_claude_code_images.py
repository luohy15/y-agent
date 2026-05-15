import json
import tempfile
import unittest
from pathlib import Path

from agent.claude_code import _claude_write_stdin


class _FakeSftp:
    def __init__(self):
        self.files = {}

    def open(self, path, mode):
        sftp = self

        class _Writer:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def write(self, data):
                sftp.files[path] = data

        return _Writer()

    def close(self):
        pass


class _FakeClient:
    def __init__(self):
        self.sftp = _FakeSftp()

    def open_sftp(self):
        return self.sftp


class ClaudeCodeImageStdinTest(unittest.TestCase):
    def test_claude_stdin_includes_image_block(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "photo.png"
            image_path.write_bytes(b"png-bytes")
            client = _FakeClient()

            _claude_write_stdin(client, "chat-1", "describe", [str(image_path)])

        payload = json.loads(client.sftp.files["/tmp/cc-chat-1.stdin"])
        content = payload["message"]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "describe"})
        self.assertEqual(content[1]["type"], "image")
        self.assertEqual(content[1]["source"]["media_type"], "image/png")
        self.assertEqual(content[1]["source"]["data"], "cG5nLWJ5dGVz")


if __name__ == "__main__":
    unittest.main()
