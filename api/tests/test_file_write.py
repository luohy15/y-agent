"""Tests for /file/write and /file/upload command construction."""

import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from starlette.datastructures import Headers, UploadFile

from api.controller import file as file_controller


def _request(user_id=1):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id))


class FileWriteTest(unittest.IsolatedAsyncioTestCase):
    async def test_write_creates_a_parent_directory_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            async def exec_local(user_id, argv, **kwargs):
                from agent.vm_command import execute_vm_command
                vm = SimpleNamespace(api_token=None, work_dir=tmp)
                return await execute_vm_command(vm, argv, stdin=kwargs.get("stdin"), work_dir=kwargs.get("work_dir"))

            with patch.object(file_controller, "_exec", exec_local):
                result = await file_controller.write_file(
                    _request(),
                    file_controller.WriteRequest(path="dir with space/file.txt", content="content"),
                    work_dir=tmp,
                )

            self.assertEqual(result, {"path": "dir with space/file.txt", "success": True})
            self.assertEqual((Path(tmp) / "dir with space" / "file.txt").read_text(), "content")

    async def test_upload_creates_a_destination_directory_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            async def exec_local(user_id, argv, **kwargs):
                from agent.vm_command import execute_vm_command
                vm = SimpleNamespace(api_token=None, work_dir=tmp)
                return await execute_vm_command(vm, argv, stdin=kwargs.get("stdin"), work_dir=kwargs.get("work_dir"))

            upload = UploadFile(
                file=io.BytesIO(b"content"),
                filename="file name.txt",
                headers=Headers({"content-type": "text/plain"}),
            )
            with patch.object(file_controller, "_exec", exec_local):
                result = await file_controller.upload_file(
                    _request(), upload, dest_dir="dir with space", work_dir=tmp
                )

            self.assertEqual(result["path"], "dir with space/file name.txt")
            self.assertEqual((Path(tmp) / "dir with space" / "file name.txt").read_bytes(), b"content")


if __name__ == "__main__":
    unittest.main()
