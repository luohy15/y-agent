import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.controller import telegram


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
            with patch.object(telegram, "IMAGE_ASSETS_DIR", assets_dir):
                self.assertEqual(telegram._resolve_send_image_path(str(image_path)), image_path.resolve())

    def test_resolve_send_image_rejects_other_paths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "photo.jpg"
            image_path.write_bytes(b"jpg")
            with patch.object(telegram, "IMAGE_ASSETS_DIR", Path(tmp_dir) / "assets" / "images"):
                with self.assertRaises(Exception):
                    telegram._resolve_send_image_path(str(image_path))


if __name__ == "__main__":
    unittest.main()
