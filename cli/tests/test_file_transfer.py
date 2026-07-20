"""Unit tests for `y file upload` / `y file download` (cli/commands/file/).

Behavior-level checks per the cli-file-transfer PRD testing decisions: group
help/usage errors, dry-run vs real flag classification, host override vs API
default resolution, upload/download argv construction (source/dest sides
swapped correctly), and tilde-safe remote mkdir quoting.

`subprocess` is a single cached module object, so `upload.py` / `download.py`
/ `_shared.py` all share the same `subprocess.run` attribute regardless of
which module they imported it through. Tests therefore patch the global
`subprocess.run` once and assert on call order/shape rather than patching it
per-module (patching both would silently make the later `with`-clause win for
every call site).
"""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from yagent.commands.file.click import file_group
from yagent.commands.file._shared import ensure_remote_dir


def _ok_result():
    result = MagicMock()
    result.returncode = 0
    result.stderr = ""
    return result


class FileGroupHelpTest(unittest.TestCase):
    def test_group_help_lists_upload_and_download(self):
        result = CliRunner().invoke(file_group, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("upload", result.output)
        self.assertIn("download", result.output)

    def test_upload_missing_sources_is_usage_error(self):
        result = CliRunner().invoke(file_group, ["upload"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("SOURCE", result.output)

    def test_download_missing_sources_is_usage_error(self):
        result = CliRunner().invoke(file_group, ["download"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("SOURCE", result.output)


class FileUploadCliTest(unittest.TestCase):
    def test_host_override_skips_api_and_builds_expected_argv(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "photo.jpg"
            source.write_bytes(b"data")

            with patch.object(subprocess, "run", return_value=_ok_result()) as run, \
                 patch("yagent.commands.file._shared.api_request") as api_request:
                result = CliRunner().invoke(
                    file_group,
                    ["upload", str(source), "--host", "me@example.com"],
                )

            self.assertEqual(result.exit_code, 0, result.output)
            api_request.assert_not_called()

            # preflight `ssh ... true`, then `mkdir -p`, then the rsync call.
            self.assertEqual(run.call_count, 3)
            preflight_cmd, mkdir_cmd, rsync_cmd = (call.args[0] for call in run.call_args_list)
            self.assertEqual(preflight_cmd[-2:], ["me@example.com", "true"])
            self.assertEqual(mkdir_cmd[-2], "me@example.com")

            # rsync argv: local source first, remote dest ("target:dest/") second.
            self.assertEqual(rsync_cmd[0], "rsync")
            self.assertEqual(rsync_cmd[-2], str(source))
            self.assertEqual(rsync_cmd[-1], "me@example.com:~/luohy15/backup/mac/")

    def test_default_host_resolves_via_vm_config_api(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "photo.jpg"
            source.write_bytes(b"data")

            with patch.object(subprocess, "run", return_value=_ok_result()), \
                 patch("yagent.commands.file._shared.api_request") as api_request:
                api_request.return_value.json.return_value = [
                    {"name": "default", "vm_name": "ssh:user@10.0.0.1"}
                ]
                result = CliRunner().invoke(file_group, ["upload", str(source)])

            self.assertEqual(result.exit_code, 0, result.output)
            api_request.assert_called_once_with("GET", "/api/vm-config/list")
            self.assertIn("Target: user@10.0.0.1", result.output)

    def test_missing_default_vm_config_raises_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "photo.jpg"
            source.write_bytes(b"data")

            with patch("yagent.commands.file._shared.api_request") as api_request:
                api_request.return_value.json.return_value = []
                result = CliRunner().invoke(file_group, ["upload", str(source)])

            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("No default VM config found", result.output)

    def test_missing_local_source_fails_before_network(self):
        with patch("yagent.commands.file._shared.api_request") as api_request:
            result = CliRunner().invoke(
                file_group, ["upload", "/does/not/exist", "--host", "me@example.com"]
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("does not exist", result.output)
        api_request.assert_not_called()

    def test_dry_run_skips_remote_mkdir_and_passes_dry_run_flag(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "photo.jpg"
            source.write_bytes(b"data")

            with patch.object(subprocess, "run", return_value=_ok_result()) as run:
                result = CliRunner().invoke(
                    file_group,
                    ["upload", str(source), "--host", "me@example.com", "-n"],
                )

            self.assertEqual(result.exit_code, 0, result.output)
            # Only the SSH preflight and the rsync call itself; no mkdir.
            self.assertEqual(run.call_count, 2)
            rsync_cmd = run.call_args_list[-1].args[0]
            self.assertIn("--dry-run", rsync_cmd)

    def test_mirror_and_checksum_flags_forwarded_to_rsync(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            source = Path(tmp_dir) / "photo.jpg"
            source.write_bytes(b"data")

            with patch.object(subprocess, "run", return_value=_ok_result()) as run:
                result = CliRunner().invoke(
                    file_group,
                    ["upload", str(source), "--host", "me@example.com", "--mirror", "--checksum"],
                )

            self.assertEqual(result.exit_code, 0, result.output)
            rsync_cmd = run.call_args_list[-1].args[0]
            self.assertIn("--delete", rsync_cmd)
            self.assertIn("--checksum", rsync_cmd)
            self.assertNotIn("--dry-run", rsync_cmd)


class FileDownloadCliTest(unittest.TestCase):
    def test_argv_swaps_source_and_dest_relative_to_upload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dest_dir = Path(tmp_dir) / "restore"

            with patch.object(subprocess, "run", return_value=_ok_result()) as run:
                result = CliRunner().invoke(
                    file_group,
                    [
                        "download", "~/luohy15/backup/mac/photo.jpg",
                        "--host", "me@example.com", "--dest", str(dest_dir),
                    ],
                )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue(dest_dir.is_dir())

            # Preflight, then the rsync call (no remote mkdir on download).
            self.assertEqual(run.call_count, 2)
            rsync_cmd = run.call_args_list[-1].args[0]
            self.assertEqual(rsync_cmd[0], "rsync")
            self.assertEqual(rsync_cmd[-2], "me@example.com:~/luohy15/backup/mac/photo.jpg")
            self.assertEqual(rsync_cmd[-1], f"{dest_dir}/")

    def test_dry_run_does_not_create_local_dest(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dest_dir = Path(tmp_dir) / "restore"

            with patch.object(subprocess, "run", return_value=_ok_result()) as run:
                result = CliRunner().invoke(
                    file_group,
                    [
                        "download", "remote.txt",
                        "--host", "me@example.com", "--dest", str(dest_dir), "-n",
                    ],
                )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertFalse(dest_dir.exists())
            rsync_cmd = run.call_args_list[-1].args[0]
            self.assertIn("--dry-run", rsync_cmd)

    def test_default_host_resolves_via_vm_config_api(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dest_dir = Path(tmp_dir) / "restore"

            with patch.object(subprocess, "run", return_value=_ok_result()), \
                 patch("yagent.commands.file._shared.api_request") as api_request:
                api_request.return_value.json.return_value = [
                    {"name": "default", "vm_name": "ssh:user@10.0.0.1"}
                ]
                result = CliRunner().invoke(
                    file_group, ["download", "remote.txt", "--dest", str(dest_dir)]
                )

            self.assertEqual(result.exit_code, 0, result.output)
            api_request.assert_called_once_with("GET", "/api/vm-config/list")


class EnsureRemoteDirQuotingTest(unittest.TestCase):
    def test_tilde_slash_path_keeps_leading_tilde_unquoted(self):
        with patch.object(subprocess, "run", return_value=_ok_result()) as run:
            ensure_remote_dir("me@example.com", [], "~/luohy15/backup/mac")

        cmd = run.call_args.args[0]
        self.assertEqual(cmd[-1], "mkdir -p ~/luohy15/backup/mac")

    def test_bare_tilde_stays_unquoted(self):
        with patch.object(subprocess, "run", return_value=_ok_result()) as run:
            ensure_remote_dir("me@example.com", [], "~")

        cmd = run.call_args.args[0]
        self.assertEqual(cmd[-1], "mkdir -p ~")

    def test_absolute_path_is_fully_quoted(self):
        with patch.object(subprocess, "run", return_value=_ok_result()) as run:
            ensure_remote_dir("me@example.com", [], "/data/backup dir")

        cmd = run.call_args.args[0]
        self.assertEqual(cmd[-1], "mkdir -p '/data/backup dir'")

    def test_mkdir_failure_raises_clean_error(self):
        failure = MagicMock()
        failure.returncode = 1
        failure.stderr = "permission denied"
        with patch.object(subprocess, "run", return_value=failure):
            with self.assertRaises(Exception) as ctx:
                ensure_remote_dir("me@example.com", [], "~/backup")
        self.assertIn("Failed to create remote dir", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
