import json
from io import BytesIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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
    def __init__(self, exec_output=""):
        self.sftp = _FakeSftp()
        self.exec_commands = []
        self.exec_output = exec_output

    def open_sftp(self):
        return self.sftp

    def exec_command(self, command):
        self.exec_commands.append(command)

        class _Channel:
            def recv_exit_status(self):
                return 0

        class _Stream:
            channel = _Channel()

            def __init__(self, data=""):
                self.data = data

            def read(self):
                return self.data.encode("utf-8")

        return None, _Stream(self.exec_output), _Stream("")


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

    def test_claude_stdin_base64_encodes_remote_only_image_over_ssh(self):
        client = _FakeClient(exec_output="cmVtb3RlLWJ5dGVz")

        _claude_write_stdin(
            client,
            "chat-1",
            "describe",
            ["/Users/roy/luohy15/assets/images/photo.jpg"],
        )

        payload = json.loads(client.sftp.files["/tmp/cc-chat-1.stdin"])
        content = payload["message"]["content"]
        self.assertEqual(content[1]["source"]["media_type"], "image/jpeg")
        self.assertEqual(content[1]["source"]["data"], "cmVtb3RlLWJ5dGVz")
        self.assertEqual(
            client.exec_commands,
            ["base64 -w0 '/Users/roy/luohy15/assets/images/photo.jpg'"],
        )

    def test_claude_stdin_base64_encodes_s3_image_locally(self):
        client = _FakeClient()
        s3 = Mock()
        s3.get_object.return_value = {
            "Body": BytesIO(b"s3-bytes"),
            "ContentType": "image/png",
        }

        with patch("boto3.client", return_value=s3):
            _claude_write_stdin(client, "chat-1", "describe", ["s3://bucket/images/photo.png"])

        payload = json.loads(client.sftp.files["/tmp/cc-chat-1.stdin"])
        content = payload["message"]["content"]
        self.assertEqual(content[1]["source"]["media_type"], "image/png")
        self.assertEqual(content[1]["source"]["data"], "czMtYnl0ZXM=")
        s3.get_object.assert_called_once_with(Bucket="bucket", Key="images/photo.png")


if __name__ == "__main__":
    unittest.main()
