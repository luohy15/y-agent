"""Unit tests for `_refresh.ensure_access_token` (todo 2872 sub-task 2):
60s expiry margin, mandatory refresh_token write-back (including keeping
the existing token when a refresh response omits a rotated one), and
`invalid_grant` flipping status to `reauth_required` without raising a
transport error.
"""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from yagent.commands.usage import _credentials as store
from yagent.commands.usage import _refresh
from yagent.commands.usage._errors import CredentialsMissingError, ReauthRequiredError


def _iso(delta_seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat().replace("+00:00", "Z")


class EnsureAccessTokenTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env_patch = patch.dict(os.environ, {"Y_AGENT_HOME": self._tmp.name})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        self._tmp.cleanup()

    def test_missing_credentials_raises(self):
        with self.assertRaises(CredentialsMissingError):
            _refresh.ensure_access_token("openai")

    def test_valid_token_returned_without_refresh(self):
        store.set_record("openai", {
            "refresh_token": "rt", "access_token": "at-valid",
            "expires_at": _iso(3600), "status": "active",
        })
        refresh_fn = MagicMock()
        with patch.dict(_refresh._oauth.REFRESH_FUNCS, {"openai": refresh_fn}):
            token = _refresh.ensure_access_token("openai")

        self.assertEqual(token, "at-valid")
        refresh_fn.assert_not_called()

    def test_token_expiring_within_60s_margin_triggers_refresh(self):
        store.set_record("openai", {
            "refresh_token": "rt-old", "access_token": "at-stale",
            "expires_at": _iso(30), "status": "active",
        })
        refresh_fn = MagicMock(return_value={
            "ok": True, "access_token": "at-new", "refresh_token": "rt-new",
            "expires_at": _iso(3600),
        })
        with patch.dict(_refresh._oauth.REFRESH_FUNCS, {"openai": refresh_fn}):
            token = _refresh.ensure_access_token("openai")

        refresh_fn.assert_called_once_with("rt-old")
        self.assertEqual(token, "at-new")

    def test_rotated_refresh_token_is_written_back(self):
        store.set_record("openai", {
            "refresh_token": "rt-old", "access_token": "at-stale",
            "expires_at": _iso(-10), "status": "active",
        })
        refresh_fn = MagicMock(return_value={
            "ok": True, "access_token": "at-new", "refresh_token": "rt-rotated",
            "expires_at": _iso(3600),
        })
        with patch.dict(_refresh._oauth.REFRESH_FUNCS, {"openai": refresh_fn}):
            _refresh.ensure_access_token("openai")

        record = store.get_record("openai")
        self.assertEqual(record["access_token"], "at-new")
        self.assertEqual(record["refresh_token"], "rt-rotated")
        self.assertEqual(record["status"], "active")

    def test_refresh_response_without_rotated_token_keeps_existing(self):
        store.set_record("xai", {
            "refresh_token": "rt-keep", "access_token": "at-stale",
            "expires_at": _iso(10), "status": "active",
        })
        refresh_fn = MagicMock(return_value={
            "ok": True, "access_token": "at-new2", "refresh_token": None,
            "expires_at": _iso(3600),
        })
        with patch.dict(_refresh._oauth.REFRESH_FUNCS, {"xai": refresh_fn}):
            _refresh.ensure_access_token("xai")

        record = store.get_record("xai")
        self.assertEqual(record["refresh_token"], "rt-keep")
        self.assertEqual(record["access_token"], "at-new2")

    def test_invalid_grant_flips_status_and_raises_reauth_required_not_a_transport_error(self):
        store.set_record("xai", {
            "refresh_token": "rt-dead", "access_token": "at-stale",
            "expires_at": _iso(-10), "status": "active",
        })
        refresh_fn = MagicMock(return_value={"ok": False, "reauth_required": True, "error": "invalid_grant"})
        with patch.dict(_refresh._oauth.REFRESH_FUNCS, {"xai": refresh_fn}):
            with self.assertRaises(ReauthRequiredError):
                _refresh.ensure_access_token("xai")

        record = store.get_record("xai")
        self.assertEqual(record["status"], "reauth_required")
        self.assertEqual(record["last_error"], "invalid_grant")

    def test_already_reauth_required_short_circuits_without_a_network_call(self):
        store.set_record("openai", {"refresh_token": "rt", "status": "reauth_required"})
        refresh_fn = MagicMock()
        with patch.dict(_refresh._oauth.REFRESH_FUNCS, {"openai": refresh_fn}):
            with self.assertRaises(ReauthRequiredError):
                _refresh.ensure_access_token("openai")
        refresh_fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
