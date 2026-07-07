"""Unit tests for api.controller.auth's signup allowlist gate (Phase 0.2 of
todo 2678): a stranger's Google account must not silently create a new
y-agent user until explicitly invited.
"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from api.controller import auth as auth_controller


class IsAllowlistedTest(unittest.TestCase):
    def test_empty_allowlist_denies_everyone(self):
        with patch.dict(os.environ, {"SIGNUP_ALLOWLIST": ""}, clear=False):
            self.assertFalse(auth_controller._is_allowlisted("stranger@example.com"))

    def test_unset_allowlist_denies_everyone(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SIGNUP_ALLOWLIST", None)
            self.assertFalse(auth_controller._is_allowlisted("stranger@example.com"))

    def test_listed_email_allowed_case_insensitive(self):
        with patch.dict(os.environ, {"SIGNUP_ALLOWLIST": "roy@example.com, Invitee@Example.com"}, clear=False):
            self.assertTrue(auth_controller._is_allowlisted("roy@example.com"))
            self.assertTrue(auth_controller._is_allowlisted("invitee@example.com"))

    def test_unlisted_email_denied(self):
        with patch.dict(os.environ, {"SIGNUP_ALLOWLIST": "roy@example.com"}, clear=False):
            self.assertFalse(auth_controller._is_allowlisted("stranger@example.com"))


class GoogleLoginGateTest(unittest.IsolatedAsyncioTestCase):
    async def test_new_unlisted_user_rejected(self):
        with (
            patch.object(auth_controller.id_token, "verify_oauth2_token", return_value={"email": "stranger@example.com"}),
            patch.object(auth_controller, "get_user_by_email", return_value=None),
            patch.object(auth_controller, "_is_allowlisted", return_value=False),
            patch.object(auth_controller, "get_or_create_user_by_email") as create,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await auth_controller.google_login(auth_controller.GoogleLoginRequest(id_token="tok"))
            self.assertEqual(ctx.exception.status_code, 403)
            create.assert_not_called()

    async def test_existing_user_bypasses_allowlist(self):
        existing = SimpleNamespace(id=1)
        with (
            patch.object(auth_controller.id_token, "verify_oauth2_token", return_value={"email": "roy@example.com"}),
            patch.object(auth_controller, "get_user_by_email", return_value=existing),
            patch.object(auth_controller, "_is_allowlisted", return_value=False),
            patch.object(auth_controller, "get_or_create_user_by_email", return_value=existing) as create,
            patch.object(auth_controller, "JWT_SECRET_KEY", "secret"),
        ):
            resp = await auth_controller.google_login(auth_controller.GoogleLoginRequest(id_token="tok"))
            self.assertEqual(resp.email, "roy@example.com")
            create.assert_called_once()

    async def test_new_allowlisted_user_created(self):
        created = SimpleNamespace(id=2)
        with (
            patch.object(auth_controller.id_token, "verify_oauth2_token", return_value={"email": "invitee@example.com"}),
            patch.object(auth_controller, "get_user_by_email", return_value=None),
            patch.object(auth_controller, "_is_allowlisted", return_value=True),
            patch.object(auth_controller, "get_or_create_user_by_email", return_value=created) as create,
            patch.object(auth_controller, "JWT_SECRET_KEY", "secret"),
        ):
            resp = await auth_controller.google_login(auth_controller.GoogleLoginRequest(id_token="tok"))
            self.assertEqual(resp.email, "invitee@example.com")
            create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
