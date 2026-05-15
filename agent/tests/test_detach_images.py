import tempfile
import unittest
from pathlib import Path

from agent.detach import _upload_images


class _FakeSftp:
    def __init__(self):
        self.puts = []

    def put(self, local_path, remote_path):
        self.puts.append((local_path, remote_path))

    def close(self):
        pass


class _FakeClient:
    def __init__(self):
        self.sftp = _FakeSftp()
        self.exec_commands = []

    def open_sftp(self):
        return self.sftp

    def exec_command(self, command):
        self.exec_commands.append(command)

        class _Channel:
            def recv_exit_status(self):
                return 0

        class _Stream:
            channel = _Channel()

            def read(self):
                return b""

        return None, _Stream(), _Stream()


class DetachImageUploadTest(unittest.TestCase):
    def test_upload_images_skips_sftp_for_remote_only_paths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            local_image = Path(tmp_dir) / "local.png"
            local_image.write_bytes(b"local")
            remote_image = "/Users/roy/luohy15/assets/images/remote.png"
            client = _FakeClient()

            result = _upload_images(client, "chat-1", [str(local_image), remote_image])

        self.assertEqual(
            result,
            ["/tmp/cc-chat-1-images/0-local.png", remote_image],
        )
        self.assertEqual(
            client.sftp.puts,
            [(str(local_image), "/tmp/cc-chat-1-images/0-local.png")],
        )


if __name__ == "__main__":
    unittest.main()
