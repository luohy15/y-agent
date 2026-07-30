"""Unit tests for `_refresh.ensure_access_token` (todo 2872 read-through
redesign): reads straight through a vendor-shaped credential file (Codex's
`tokens.*` shape / Grok's dynamic `{issuer}::{client_id}` nesting), 60s
expiry margin, mandatory write-back of the (possibly rotated) grant into
that SAME file, and `invalid_grant` flipping to `ReauthRequiredError`
without raising a transport error and without touching the file.
"""

import base64
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from yagent.commands.usage import _refresh
from yagent.commands.usage._errors import CredentialsMissingError, ReauthRequiredError


def _iso(delta_seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat().replace("+00:00", "Z")


def _jwt(exp_delta_seconds: float) -> str:
    exp = int((datetime.now(timezone.utc) + timedelta(seconds=exp_delta_seconds)).timestamp())
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=").decode()
    return f"header.{payload}.sig"


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(path, 0o600)


def _codex_file(*, access_expires_in: float, refresh_token="rt-old", account_id="acct-1") -> dict:
    return {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": "irrelevant",
            "access_token": _jwt(access_expires_in),
            "refresh_token": refresh_token,
            "account_id": account_id,
        },
        "last_refresh": "2026-01-01T00:00:00Z",
    }


def _grok_file(*, expires_at: str, refresh_token="rt-old") -> dict:
    return {
        "https://auth.x.ai::client-123": {
            "key": "at-stale",
            "auth_mode": "oidc",
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "oidc_issuer": "https://auth.x.ai",
            "oidc_client_id": "client-123",
        }
    }


class EnsureAccessTokenTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._openai_path = Path(self._tmp.name) / "codex-auth.json"
        self._xai_path = Path(self._tmp.name) / "grok-auth.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_raises_credentials_missing(self):
        with self.assertRaises(CredentialsMissingError):
            _refresh.ensure_access_token("openai", path=self._openai_path)

    def test_no_refresh_token_raises_credentials_missing(self):
        data = _codex_file(access_expires_in=3600)
        del data["tokens"]["refresh_token"]
        _write(self._openai_path, data)
        with self.assertRaises(CredentialsMissingError):
            _refresh.ensure_access_token("openai", path=self._openai_path)

    def test_valid_token_returned_without_refresh_or_write(self):
        _write(self._openai_path, _codex_file(access_expires_in=3600))
        before = self._openai_path.read_bytes()
        refresh_fn = MagicMock()
        with patch.dict(_oauth_funcs(), {"openai": refresh_fn}):
            token = _refresh.ensure_access_token("openai", path=self._openai_path)

        refresh_fn.assert_not_called()
        self.assertTrue(token)
        self.assertEqual(self._openai_path.read_bytes(), before)

    def test_token_expiring_within_60s_margin_triggers_refresh(self):
        _write(self._openai_path, _codex_file(access_expires_in=30))
        refresh_fn = MagicMock(return_value={
            "ok": True, "access_token": "at-new", "refresh_token": "rt-new",
            "expires_at": _iso(3600),
        })
        with patch.dict(_oauth_funcs(), {"openai": refresh_fn}):
            token = _refresh.ensure_access_token("openai", path=self._openai_path)

        refresh_fn.assert_called_once_with("rt-old")
        self.assertEqual(token, "at-new")

    def test_rotated_refresh_token_is_written_back_into_the_vendor_file(self):
        _write(self._openai_path, _codex_file(access_expires_in=-10))
        refresh_fn = MagicMock(return_value={
            "ok": True, "access_token": "at-new", "refresh_token": "rt-rotated",
            "expires_at": _iso(3600), "id_token": "id-new",
        })
        with patch.dict(_oauth_funcs(), {"openai": refresh_fn}):
            _refresh.ensure_access_token("openai", path=self._openai_path)

        data = json.loads(self._openai_path.read_text(encoding="utf-8"))
        self.assertEqual(data["tokens"]["access_token"], "at-new")
        self.assertEqual(data["tokens"]["refresh_token"], "rt-rotated")
        self.assertEqual(data["tokens"]["id_token"], "id-new")
        # Untouched fields survive exactly.
        self.assertEqual(data["tokens"]["account_id"], "acct-1")
        self.assertEqual(data["auth_mode"], "chatgpt")
        self.assertIsNone(data["OPENAI_API_KEY"])

    def test_refresh_response_without_rotated_token_keeps_existing(self):
        _write(self._xai_path, _grok_file(expires_at=_iso(10)))
        refresh_fn = MagicMock(return_value={
            "ok": True, "access_token": "at-new2", "refresh_token": None,
            "expires_at": _iso(3600),
        })
        with patch.dict(_oauth_funcs(), {"xai": refresh_fn}):
            _refresh.ensure_access_token("xai", path=self._xai_path)

        data = json.loads(self._xai_path.read_text(encoding="utf-8"))
        record = data["https://auth.x.ai::client-123"]
        self.assertEqual(record["refresh_token"], "rt-old")
        self.assertEqual(record["key"], "at-new2")

    def test_grok_dynamic_issuer_client_id_nesting_is_preserved_on_write_back(self):
        _write(self._xai_path, _grok_file(expires_at=_iso(-10)))
        refresh_fn = MagicMock(return_value={
            "ok": True, "access_token": "at-new", "refresh_token": "rt-rotated",
            "expires_at": _iso(21600),
        })
        with patch.dict(_oauth_funcs(), {"xai": refresh_fn}):
            _refresh.ensure_access_token("xai", path=self._xai_path)

        data = json.loads(self._xai_path.read_text(encoding="utf-8"))
        self.assertEqual(set(data.keys()), {"https://auth.x.ai::client-123"})
        record = data["https://auth.x.ai::client-123"]
        self.assertEqual(record["key"], "at-new")
        self.assertEqual(record["refresh_token"], "rt-rotated")
        # Untouched fields survive exactly, including the nesting key itself.
        self.assertEqual(record["auth_mode"], "oidc")
        self.assertEqual(record["oidc_issuer"], "https://auth.x.ai")
        self.assertEqual(record["oidc_client_id"], "client-123")

    def test_invalid_grant_flips_to_reauth_required_and_leaves_file_untouched(self):
        _write(self._xai_path, _grok_file(expires_at=_iso(-10)))
        before = self._xai_path.read_bytes()
        refresh_fn = MagicMock(return_value={"ok": False, "reauth_required": True, "error": "invalid_grant"})
        with patch.dict(_oauth_funcs(), {"xai": refresh_fn}):
            with self.assertRaises(ReauthRequiredError):
                _refresh.ensure_access_token("xai", path=self._xai_path)

        self.assertEqual(self._xai_path.read_bytes(), before)

    def test_file_mode_is_preserved_across_a_refresh_write_back(self):
        _write(self._openai_path, _codex_file(access_expires_in=-10))
        os.chmod(self._openai_path, 0o600)
        refresh_fn = MagicMock(return_value={
            "ok": True, "access_token": "at-new", "refresh_token": "rt-new", "expires_at": _iso(3600),
        })
        with patch.dict(_oauth_funcs(), {"openai": refresh_fn}):
            _refresh.ensure_access_token("openai", path=self._openai_path)

        mode = self._openai_path.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)


def _oauth_funcs():
    return _refresh._oauth.REFRESH_FUNCS


if __name__ == "__main__":
    unittest.main()
