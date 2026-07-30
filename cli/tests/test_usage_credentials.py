"""Unit tests for the vendor-file read-through/write-back machinery in
`_credentials.py` (todo 2872 read-through redesign) -- the piece the task
calls out as the core risk: atomic replace, lock behaviour under concurrent
refresh, exact per-provider shape preservation (including Grok's dynamic
`{issuer}::{client_id}` nesting), and mode preservation.
"""

import fcntl
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from yagent.commands.usage import _credentials as vendor


class SaveVendorFileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = Path(self._tmp.name) / "auth.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_atomic_replace_leaves_no_tmp_file_behind(self):
        self._path.write_text(json.dumps({"a": 1}), encoding="utf-8")
        os.chmod(self._path, 0o600)
        vendor.save_vendor_file(self._path, {"a": 2})

        self.assertEqual(json.loads(self._path.read_text(encoding="utf-8")), {"a": 2})
        leftovers = [p for p in Path(self._tmp.name).iterdir() if p.name.startswith(".auth.json.")]
        self.assertEqual(leftovers, [])

    def test_mode_is_preserved_from_the_original_file(self):
        self._path.write_text(json.dumps({"a": 1}), encoding="utf-8")
        os.chmod(self._path, 0o600)
        vendor.save_vendor_file(self._path, {"a": 2})
        self.assertEqual(self._path.stat().st_mode & 0o777, 0o600)

    def test_never_creates_a_world_or_group_readable_file(self):
        self._path.write_text(json.dumps({"a": 1}), encoding="utf-8")
        os.chmod(self._path, 0o600)
        vendor.save_vendor_file(self._path, {"a": 2, "secret": "token-material"})
        self.assertEqual(self._path.stat().st_mode & 0o077, 0)

    def test_a_reader_never_observes_a_partial_write(self):
        """Simulate a concurrent reader polling mid-write: since the writer
        builds the full temp file then `os.replace`s it in one step, every
        read anyone can observe is either the old, complete file or the
        new, complete file -- never a half-written one."""
        self._path.write_text(json.dumps({"a": 1}), encoding="utf-8")
        os.chmod(self._path, 0o600)

        big_payload = {"a": 2, "padding": "x" * 200_000}
        observations = []
        stop = threading.Event()

        def _poll():
            while not stop.is_set():
                try:
                    text = self._path.read_text(encoding="utf-8")
                    json.loads(text)  # must always be complete, valid JSON
                except (json.JSONDecodeError, FileNotFoundError, OSError):
                    observations.append("BAD")

        poller = threading.Thread(target=_poll)
        poller.start()
        for _ in range(20):
            vendor.save_vendor_file(self._path, big_payload)
        stop.set()
        poller.join()

        self.assertEqual(observations, [])


class MutateVendorFileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = Path(self._tmp.name) / "auth.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, data: dict) -> None:
        self._path.write_text(json.dumps(data), encoding="utf-8")
        os.chmod(self._path, 0o600)

    def test_missing_file_is_a_no_op(self):
        called = []
        result = vendor.mutate_vendor_file(self._path, lambda d: called.append(d) or d)
        self.assertIsNone(result)
        self.assertEqual(called, [])

    def test_fn_returning_none_does_not_write(self):
        self._write({"a": 1})
        before = self._path.read_bytes()
        result = vendor.mutate_vendor_file(self._path, lambda d: None)
        self.assertIsNone(result)
        self.assertEqual(self._path.read_bytes(), before)

    def test_fn_return_value_is_persisted(self):
        self._write({"a": 1})

        def _bump(data):
            data["a"] += 1
            return data

        vendor.mutate_vendor_file(self._path, _bump)
        self.assertEqual(json.loads(self._path.read_text(encoding="utf-8")), {"a": 2})

    def test_concurrent_mutations_serialize_instead_of_losing_an_update(self):
        """Two threads incrementing the same counter under the lock must not
        lose an update to a race -- this is the generic form of "two
        y-agent readers refreshing the same provider can't clobber each
        other"."""
        self._write({"counter": 0})

        def _increment(data):
            current = data["counter"]
            time.sleep(0.01)  # widen the window a lost update would need
            data["counter"] = current + 1
            return data

        threads = [threading.Thread(target=lambda: vendor.mutate_vendor_file(self._path, _increment))
                   for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(json.loads(self._path.read_text(encoding="utf-8"))["counter"], 8)

    def test_lock_file_is_exclusive_while_held(self):
        self._write({"a": 1})
        lock_path = vendor._lock_path(self._path)
        held = threading.Event()
        release = threading.Event()

        def _hold_lock():
            def _fn(data):
                held.set()
                release.wait(timeout=5)
                return data

            vendor.mutate_vendor_file(self._path, _fn)

        holder = threading.Thread(target=_hold_lock)
        holder.start()
        held.wait(timeout=5)

        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
            release.set()
            holder.join()


class OpenaiGrokShapeRoundTripTest(unittest.TestCase):
    """Exact shape preservation per provider, including unrelated fields and
    Grok's dynamic nesting key."""

    def test_codex_shape_round_trip_preserves_every_unrelated_field(self):
        original = {
            "auth_mode": "chatgpt",
            "OPENAI_API_KEY": None,
            "tokens": {
                "id_token": "id-old",
                "access_token": "at-old",
                "refresh_token": "rt-old",
                "account_id": "acct-1",
            },
            "last_refresh": "2026-01-01T00:00:00Z",
        }
        result = {
            "ok": True, "access_token": "at-new", "refresh_token": "rt-new",
            "expires_at": "2026-01-02T00:00:00Z", "id_token": "id-new",
        }
        new_data = vendor.apply_refresh("openai", dict(original, tokens=dict(original["tokens"])), result)

        self.assertEqual(new_data["auth_mode"], "chatgpt")
        self.assertIsNone(new_data["OPENAI_API_KEY"])
        self.assertEqual(new_data["tokens"]["account_id"], "acct-1")
        self.assertEqual(new_data["tokens"]["access_token"], "at-new")
        self.assertEqual(new_data["tokens"]["refresh_token"], "rt-new")
        self.assertEqual(new_data["tokens"]["id_token"], "id-new")
        self.assertIn("last_refresh", new_data)

    def test_grok_dynamic_nesting_key_is_preserved_verbatim(self):
        key = "https://auth.x.ai::b1a00492-073a-47ea-816f-4c329264a828"
        original = {
            key: {
                "key": "at-old",
                "auth_mode": "oidc",
                "email": "user@example.com",
                "refresh_token": "rt-old",
                "expires_at": "2026-01-01T00:00:00Z",
                "oidc_issuer": "https://auth.x.ai",
                "oidc_client_id": "b1a00492-073a-47ea-816f-4c329264a828",
            }
        }
        result = {"ok": True, "access_token": "at-new", "refresh_token": "rt-new", "expires_at": "2026-01-02T00:00:00Z"}
        new_data = vendor.apply_refresh("xai", {k: dict(v) for k, v in original.items()}, result)

        self.assertEqual(set(new_data.keys()), {key})
        record = new_data[key]
        self.assertEqual(record["key"], "at-new")
        self.assertEqual(record["refresh_token"], "rt-new")
        self.assertEqual(record["email"], "user@example.com")
        self.assertEqual(record["oidc_issuer"], "https://auth.x.ai")
        self.assertEqual(record["oidc_client_id"], "b1a00492-073a-47ea-816f-4c329264a828")

    def test_extract_grant_reads_both_shapes(self):
        codex_data = {"tokens": {"refresh_token": "rt", "access_token": "at"}}
        self.assertEqual(vendor.extract_grant("openai", codex_data)["refresh_token"], "rt")

        grok_data = {"issuer::client": {"refresh_token": "rt2", "key": "at2", "expires_at": "x"}}
        grant = vendor.extract_grant("xai", grok_data)
        self.assertEqual(grant["refresh_token"], "rt2")
        self.assertEqual(grant["access_token"], "at2")
        self.assertEqual(grant["expires_at"], "x")


class LoadVendorFileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = Path(self._tmp.name) / "auth.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_is_none(self):
        self.assertIsNone(vendor.load_vendor_file(self._path))

    def test_empty_file_is_none(self):
        self._path.write_text("", encoding="utf-8")
        self.assertIsNone(vendor.load_vendor_file(self._path))

    def test_invalid_json_is_none_not_a_crash(self):
        self._path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(vendor.load_vendor_file(self._path))

    def test_valid_json_round_trips(self):
        self._path.write_text(json.dumps({"a": 1}), encoding="utf-8")
        self.assertEqual(vendor.load_vendor_file(self._path), {"a": 1})


if __name__ == "__main__":
    unittest.main()
