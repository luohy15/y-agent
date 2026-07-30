"""Mocked-httpx unit tests for the OpenAI/xAI refresh request shapes
(todo 2872 sub-task 2): exact URL / method / body / headers per provider,
plus `invalid_grant` flipping the result instead of raising.
"""

import unittest
from unittest.mock import MagicMock, patch

from yagent.commands.usage import _oauth


def _response(status_code=200, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_body or {})
    if status_code >= 400:
        resp.raise_for_status = MagicMock(side_effect=RuntimeError(f"http {status_code}"))
    else:
        resp.raise_for_status = MagicMock()
    return resp


class RefreshOpenaiTest(unittest.TestCase):
    def test_request_shape(self):
        resp = _response(200, {
            "access_token": "at-1",
            "refresh_token": "rt-2",
            "expires_in": 3600,
        })
        with patch("yagent.commands.usage._oauth.httpx.post", return_value=resp) as post:
            result = _oauth.refresh_openai("rt-old")

        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://auth.openai.com/oauth/token")
        self.assertEqual(args[0], _oauth.OPENAI_TOKEN_URL)
        self.assertEqual(kwargs["data"], {
            "grant_type": "refresh_token",
            "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
            "refresh_token": "rt-old",
            "scope": "openid profile email",
        })
        self.assertEqual(kwargs["headers"], {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["access_token"], "at-1")
        self.assertEqual(result["refresh_token"], "rt-2")
        self.assertIn("expires_at", result)

    def test_extracts_chatgpt_account_id_from_id_token_claim(self):
        import base64
        import json as _json

        claims = _json.dumps({
            "https://api.openai.com/auth": {"chatgpt_account_id": "acct-123"},
        }).encode()
        payload = base64.urlsafe_b64encode(claims).rstrip(b"=").decode()
        id_token = f"header.{payload}.sig"

        resp = _response(200, {"access_token": "at-1", "id_token": id_token})
        with patch("yagent.commands.usage._oauth.httpx.post", return_value=resp):
            result = _oauth.refresh_openai("rt-old")

        self.assertEqual(result["extra"], {"chatgpt_account_id": "acct-123"})

    def test_invalid_grant_returns_reauth_required_without_raising(self):
        resp = _response(400, {"error": "invalid_grant"})
        with patch("yagent.commands.usage._oauth.httpx.post", return_value=resp):
            result = _oauth.refresh_openai("rt-dead")

        self.assertEqual(result, {"ok": False, "reauth_required": True, "error": "invalid_grant"})

    def test_openais_real_nested_error_shape_returns_reauth_required_without_raising(self):
        # Live-verified (todo 2872): a refresh_token superseded by a fresh
        # `codex login` gets a 401 with a NESTED error object, not the flat
        # RFC 6749 `{"error": "invalid_grant"}` string -- if this regresses,
        # a real dead OpenAI grant raises a bare HTTPStatusError instead of
        # degrading to reauth_required.
        resp = _response(401, {
            "error": {
                "message": "Your session has ended. Please log in again.",
                "type": "invalid_request_error",
                "param": None,
                "code": "refresh_token_invalidated",
            }
        })
        with patch("yagent.commands.usage._oauth.httpx.post", return_value=resp):
            result = _oauth.refresh_openai("rt-superseded")

        self.assertEqual(result, {"ok": False, "reauth_required": True, "error": "invalid_grant"})

    def test_other_http_error_raises(self):
        resp = _response(500, {"error": "server_error"})
        with patch("yagent.commands.usage._oauth.httpx.post", return_value=resp):
            with self.assertRaises(RuntimeError):
                _oauth.refresh_openai("rt-old")


class RefreshXaiTest(unittest.TestCase):
    def test_request_shape_and_rotated_refresh_token(self):
        resp = _response(200, {"access_token": "at-x", "refresh_token": "rt-rotated"})
        with patch("yagent.commands.usage._oauth.httpx.post", return_value=resp) as post:
            result = _oauth.refresh_xai("rt-old")

        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://auth.x.ai/oauth2/token")
        self.assertEqual(args[0], _oauth.XAI_TOKEN_URL)
        self.assertEqual(kwargs["data"], {
            "grant_type": "refresh_token",
            "client_id": "b1a00492-073a-47ea-816f-4c329264a828",
            "refresh_token": "rt-old",
        })
        self.assertEqual(kwargs["headers"], {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["access_token"], "at-x")
        self.assertEqual(result["refresh_token"], "rt-rotated")

    def test_missing_rotated_refresh_token_is_none_not_fabricated(self):
        resp = _response(200, {"access_token": "at-x"})
        with patch("yagent.commands.usage._oauth.httpx.post", return_value=resp):
            result = _oauth.refresh_xai("rt-old")

        self.assertIsNone(result["refresh_token"])

    def test_invalid_grant_returns_reauth_required_without_raising(self):
        resp = _response(401, {"error": "invalid_grant"})
        with patch("yagent.commands.usage._oauth.httpx.post", return_value=resp):
            result = _oauth.refresh_xai("rt-dead")

        self.assertEqual(result, {"ok": False, "reauth_required": True, "error": "invalid_grant"})

    def test_other_http_error_raises(self):
        resp = _response(503, {"error": "unavailable"})
        with patch("yagent.commands.usage._oauth.httpx.post", return_value=resp):
            with self.assertRaises(RuntimeError):
                _oauth.refresh_xai("rt-old")


if __name__ == "__main__":
    unittest.main()
