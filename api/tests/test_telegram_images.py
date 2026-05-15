import tempfile
import unittest
import base64
import errno
from pathlib import Path
from unittest.mock import patch

from api.controller import telegram
from api.util import images


class TelegramImageStorageTest(unittest.TestCase):
    def test_save_telegram_image_uses_assets_dir_and_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(telegram, "IMAGE_ASSETS_DIR", Path(tmp_dir)):
                with patch.object(telegram, "get_utc_iso8601_timestamp", return_value="2026-05-15T08:17:09.123Z"):
                    image_path = telegram._save_telegram_image(b"image-bytes", "j.pg", "bad/file:id_123456789")

            self.assertEqual(image_path.parent, Path(tmp_dir))
            self.assertEqual(image_path.name, "telegram-2026-05-15T081709.123Z-id_123456789.jpg")
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

    def test_save_send_image_upload_uses_assets_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            upload = telegram.TelegramImageUpload(
                filename="../photo.png",
                content_base64=base64.b64encode(b"png").decode("ascii"),
            )
            with patch("api.util.images.IMAGE_ASSETS_DIR", Path(tmp_dir)):
                image_path = images.save_send_image_upload(upload, prefix="telegram-upload")

            self.assertEqual(image_path.parent, Path(tmp_dir).resolve())
            self.assertRegex(image_path.name, r"telegram-upload-\d{8}T\d{6}\.\d{3}Z-photo-[0-9a-f]{8}\.png")
            self.assertEqual(image_path.read_bytes(), b"png")

    def test_save_send_image_upload_falls_back_to_tmp_on_readonly_assets_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            upload = telegram.TelegramImageUpload(
                filename="photo.png",
                content_base64=base64.b64encode(b"png").decode("ascii"),
            )
            readonly_dir = Path(tmp_dir) / "readonly" / "images"
            tmp_assets_dir = Path(tmp_dir) / "tmp" / "images"

            original_mkdir = Path.mkdir

            def fake_mkdir(self, *args, **kwargs):
                if self == readonly_dir.resolve():
                    raise OSError(errno.EROFS, "Read-only file system")
                return original_mkdir(self, *args, **kwargs)

            with patch("api.util.images.IMAGE_ASSETS_DIR", readonly_dir):
                with patch("api.util.images.Path", wraps=Path) as path_cls:
                    path_cls.side_effect = lambda *args, **kwargs: tmp_assets_dir if args == ("/tmp/y-agent-images",) else Path(*args, **kwargs)
                    with patch.object(Path, "mkdir", fake_mkdir):
                        image_path = images.save_send_image_upload(upload, prefix="telegram-upload")

            self.assertEqual(image_path.parent, tmp_assets_dir)
            self.assertEqual(image_path.read_bytes(), b"png")


if __name__ == "__main__":
    unittest.main()
