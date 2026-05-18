import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from agent.detach import DetachBackendSpec, _download_s3_to_tmp, _start_detached_tmux, _upload_images


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

    def test_upload_images_downloads_s3_before_sftp(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            s3 = Mock()

            def download_file(bucket, key, target):
                Path(target).write_bytes(b"s3-bytes")

            s3.download_file.side_effect = download_file
            client = _FakeClient()
            with patch.dict("os.environ", {"Y_AGENT_IMAGE_TMP_DIR": tmp_dir}):
                with patch("boto3.client", return_value=s3):
                    result = _upload_images(client, "chat-1", ["s3://bucket/images/photo.png"])

        self.assertEqual(result, ["/tmp/cc-chat-1-images/0-photo.png"])
        s3.download_file.assert_called_once_with("bucket", "images/photo.png", str(Path(tmp_dir) / "cc-chat-1-images" / "photo.png"))
        self.assertEqual(client.sftp.puts[0][1], "/tmp/cc-chat-1-images/0-photo.png")
        self.assertFalse(Path(client.sftp.puts[0][0]).exists())


class DetachTmuxHeartbeatTest(unittest.TestCase):
    def test_start_detached_tmux_wraps_exec_with_last_seen_heartbeat(self):
        client = _FakeClient()
        spec = DetachBackendSpec(
            build_exec=lambda cmd, chat_id, prompt, images: " ".join(cmd),
            parse_initial=lambda obj: None,
            upload_images=False,
        )

        with patch("agent.detach.asyncio.sleep", new_callable=AsyncMock):
            asyncio.run(
                _start_detached_tmux(
                    ["echo", "ok"],
                    "prompt",
                    "/tmp/work dir",
                    "chat-1",
                    vm_config=None,
                    spec=spec,
                    ssh_client=client,
                )
            )

        tmux_cmd = next(command for command in client.exec_commands if command.startswith("tmux new-session"))
        self.assertIn("date +%s > /tmp/ec2-ssh-last-seen;", tmux_cmd)
        self.assertIn("while :; do date +%s > /tmp/ec2-ssh-last-seen; sleep 60; done", tmux_cmd)
        self.assertIn("HEARTBEAT_PID=$!;", tmux_cmd)
        self.assertIn("EC=$?; kill $HEARTBEAT_PID 2>/dev/null; echo $EC >", tmux_cmd)
        self.assertIn("/tmp/cc-chat-1.exit", tmux_cmd)


if __name__ == "__main__":
    unittest.main()
