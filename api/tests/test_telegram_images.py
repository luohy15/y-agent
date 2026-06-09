import tempfile
import unittest
import base64
import errno
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from api.controller import telegram
from api.util import images


class TelegramImageStorageTest(unittest.TestCase):
    def test_save_telegram_image_uses_assets_dir_and_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("api.util.images.IMAGE_ASSETS_DIR", Path(tmp_dir)):
                with patch("api.util.images.datetime") as dt:
                    dt.now.return_value.strftime.return_value = "20260515T081709.123456"
                    image_path = telegram._save_telegram_image(b"image-bytes", "j.pg", "bad/file:id_123456789")

            image_path = Path(image_path)
            self.assertEqual(image_path.parent, Path(tmp_dir).resolve())
            self.assertRegex(image_path.name, r"telegram-id_123456789-.*\.jpg")
            self.assertEqual(image_path.read_bytes(), b"image-bytes")

    def test_resolve_send_image_requires_assets_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            assets_dir = Path(tmp_dir) / "assets" / "images"
            assets_dir.mkdir(parents=True)
            image_path = assets_dir / "photo.jpg"
            image_path.write_bytes(b"jpg")
            with patch("api.util.images.IMAGE_ASSETS_DIR", assets_dir):
                self.assertEqual(images.resolve_send_image_path(str(image_path)), image_path.resolve())

    def test_resolve_send_image_rejects_other_paths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "photo.jpg"
            image_path.write_bytes(b"jpg")
            with patch("api.util.images.IMAGE_ASSETS_DIR", Path(tmp_dir) / "assets" / "images"):
                with self.assertRaises(Exception):
                    images.resolve_send_image_path(str(image_path))

    def test_resolve_message_image_paths_allows_missing_assets_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            assets_dir = Path(tmp_dir) / "assets" / "images"
            image_path = assets_dir / "missing.jpg"
            with patch("api.util.images.IMAGE_ASSETS_DIR", assets_dir):
                self.assertEqual(images.resolve_message_image_paths([str(image_path)], None), [str(image_path.resolve())])

    def test_resolve_message_image_paths_passes_remote_urls_through(self):
        image_refs = ["https://example.com/photo.jpg"]
        self.assertEqual(images.resolve_message_image_paths(image_refs, None), image_refs)

    def test_resolve_message_image_paths_rejects_s3_refs(self):
        with self.assertRaises(Exception):
            images.resolve_message_image_paths(["s3://bucket/images/photo.png"], None)

    def test_save_send_image_upload_uses_assets_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            upload = telegram.TelegramImageUpload(
                filename="../photo.png",
                content_base64=base64.b64encode(b"png").decode("ascii"),
            )
            with patch("api.util.images.IMAGE_ASSETS_DIR", Path(tmp_dir)):
                image_path = images.save_send_image_upload(upload, prefix="telegram-upload")

            image_path = Path(image_path)
            self.assertEqual(image_path.parent, Path(tmp_dir).resolve())
            self.assertRegex(image_path.name, r"telegram-upload-photo-\d{8}T\d{6}\.\d{3}Z-[0-9a-f]{8}\.png")
            self.assertEqual(image_path.read_bytes(), b"png")

    def test_save_send_image_upload_ssh_pushes_on_readonly_assets_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            upload = telegram.TelegramImageUpload(
                filename="photo.png",
                content_base64=base64.b64encode(b"png").decode("ascii"),
            )
            readonly_dir = Path(tmp_dir) / "readonly" / "images"
            vm_config = Mock(vm_name="ssh:ec2", api_token="key")

            original_mkdir = Path.mkdir

            def fake_mkdir(self, *args, **kwargs):
                if self == readonly_dir.resolve():
                    raise OSError(errno.EROFS, "Read-only file system")
                return original_mkdir(self, *args, **kwargs)

            with patch("api.util.images.IMAGE_ASSETS_DIR", readonly_dir):
                with patch.object(Path, "mkdir", fake_mkdir):
                    with patch("api.util.images.ssh_put_image_bytes", return_value=str(readonly_dir / "photo.png")) as ssh_put:
                        image_path = images.save_send_image_upload(upload, prefix="telegram-upload", vm_config=vm_config)

            self.assertEqual(image_path, str(readonly_dir / "photo.png"))
            ssh_put.assert_called_once()
            self.assertEqual(ssh_put.call_args.args[0], b"png")
            self.assertEqual(ssh_put.call_args.kwargs["vm_config"], vm_config)

    def test_save_image_bytes_readonly_without_vm_config_raises_service_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            readonly_dir = Path(tmp_dir) / "readonly" / "images"

            def fake_mkdir(self, *args, **kwargs):
                if self == readonly_dir.resolve():
                    raise OSError(errno.EROFS, "Read-only file system")
                return None

            with patch("api.util.images.IMAGE_ASSETS_DIR", readonly_dir):
                with patch.object(Path, "mkdir", fake_mkdir):
                    with self.assertRaises(Exception) as ctx:
                        images.save_image_bytes(b"png", prefix="telegram", suffix=".png")

            self.assertEqual(ctx.exception.status_code, 503)

    def test_ssh_put_image_bytes_writes_remote_file(self):
        vm_config = Mock(vm_name="ssh:ec2", api_token="key")
        client = Mock()
        sftp = Mock()
        remote_file = Mock()
        open_handle = MagicMock()
        open_handle.__enter__.return_value = remote_file
        sftp.open.return_value = open_handle
        client.open_sftp.return_value = sftp

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("api.util.images.IMAGE_ASSETS_DIR", Path(tmp_dir)):
                with patch("agent.ec2_wake.ensure_and_touch_vm") as ensure_vm:
                    with patch("api.util.images._get_ssh_pool") as get_pool:
                        get_pool.return_value.get_or_create.return_value = client
                        image_path = images.ssh_put_image_bytes(b"png", prefix="telegram", suffix=".png", vm_config=vm_config)

        ensure_vm.assert_called_once_with(vm_config)
        sftp.open.assert_called_once()
        remote_file.write.assert_called_once_with(b"png")
        self.assertTrue(image_path.endswith(".png"))


if __name__ == "__main__":
    unittest.main()
