import tempfile
import unittest
import base64
import errno
import os
from pathlib import Path
from unittest.mock import Mock, patch

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
        image_refs = ["https://example.com/photo.jpg", "s3://bucket/images/photo.png"]
        self.assertEqual(images.resolve_message_image_paths(image_refs, None), image_refs)

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

    def test_save_send_image_upload_falls_back_to_s3_on_readonly_assets_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            upload = telegram.TelegramImageUpload(
                filename="photo.png",
                content_base64=base64.b64encode(b"png").decode("ascii"),
            )
            readonly_dir = Path(tmp_dir) / "readonly" / "images"
            s3 = Mock()

            original_mkdir = Path.mkdir

            def fake_mkdir(self, *args, **kwargs):
                if self == readonly_dir.resolve():
                    raise OSError(errno.EROFS, "Read-only file system")
                return original_mkdir(self, *args, **kwargs)

            with patch("api.util.images.IMAGE_ASSETS_DIR", readonly_dir):
                with patch.dict(os.environ, {"Y_AGENT_S3_BUCKET": "bucket"}):
                    with patch("boto3.client", return_value=s3):
                        with patch.object(Path, "mkdir", fake_mkdir):
                            image_path = images.save_send_image_upload(upload, prefix="telegram-upload")

            self.assertRegex(image_path, r"^s3://bucket/images/telegram-upload-photo-.*\.png$")
            s3.put_object.assert_called_once()
            self.assertEqual(s3.put_object.call_args.kwargs["Body"], b"png")

    def test_save_image_bytes_readonly_without_bucket_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            readonly_dir = Path(tmp_dir) / "readonly" / "images"

            def fake_mkdir(self, *args, **kwargs):
                if self == readonly_dir.resolve():
                    raise OSError(errno.EROFS, "Read-only file system")
                return None

            with patch("api.util.images.IMAGE_ASSETS_DIR", readonly_dir):
                with patch.dict(os.environ, {}, clear=True):
                    with patch.object(Path, "mkdir", fake_mkdir):
                        with self.assertRaises(RuntimeError):
                            images.save_image_bytes(b"png", prefix="telegram", suffix=".png")


if __name__ == "__main__":
    unittest.main()
