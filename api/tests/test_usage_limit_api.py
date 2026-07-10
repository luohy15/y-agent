"""Unit tests for the authenticated GET /usage/limits endpoint
(api.controller.model_usage.limits). storage.service.model_usage_limits is
mocked; nothing touches a real database or CRS."""

import unittest
import os
from types import SimpleNamespace
from unittest.mock import patch

from api.controller import model_usage as usage_controller


def _request(user_id=123):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id))


class LimitsEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def test_delegates_to_the_limits_service_for_the_request_user(self):
        envelope = {"providers": [], "errors": []}
        with patch.object(
            usage_controller.limits_service, "get_limit_status", return_value=envelope
        ) as get_limit_status:
            result = await usage_controller.limits(_request(user_id=456))

        get_limit_status.assert_called_once_with(456)
        self.assertEqual(result, {**envelope, "timezone": "Asia/Shanghai"})

    async def test_returns_the_service_envelope_unchanged(self):
        envelope = {
            "providers": [
                {
                    "backend": "claude_code",
                    "provider": "anthropic",
                    "account_id": "acct-1",
                    "account_name": "Claude subscription",
                    "observed_at": "2026-07-10T15:00:00Z",
                    "source": "anthropic_oauth_usage",
                    "availability": "available",
                    "freshness": "fresh",
                    "error": None,
                    "windows": {
                        "five_hour": {"used_percent": 42, "remaining_percent": 58, "reset_at": "2026-07-10T20:00:00Z"},
                        "one_week": {"used_percent": 18, "remaining_percent": 82, "reset_at": "2026-07-15T00:00:00Z"},
                    },
                    "extra_windows": {},
                }
            ],
            "errors": [],
        }
        with patch.object(usage_controller.limits_service, "get_limit_status", return_value=envelope):
            result = await usage_controller.limits(_request())

        self.assertEqual(result, {**envelope, "timezone": "Asia/Shanghai"})
        self.assertNotIn("id", result["providers"][0])
        self.assertNotIn("user_id", result["providers"][0])

    async def test_returns_one_selected_card_per_backend_and_separate_partial_errors(self):
        envelope = {
            "providers": [
                {"backend": "claude_code", "account_id": "acct-claude", "freshness": "fresh"},
                {"backend": "codex", "account_id": "acct-codex", "freshness": "fresh"},
            ],
            "errors": [{"origin": "https://old-relay.example", "error": "timeout"}],
        }
        with patch.object(usage_controller.limits_service, "get_limit_status", return_value=envelope):
            result = await usage_controller.limits(_request())

        self.assertEqual([provider["backend"] for provider in result["providers"]], ["claude_code", "codex"])
        self.assertEqual(result["errors"], envelope["errors"])

    async def test_returns_configured_timezone(self):
        with (
            patch.dict(os.environ, {"Y_AGENT_TIMEZONE": "America/Los_Angeles"}),
            patch.object(usage_controller.limits_service, "get_limit_status", return_value={"providers": [], "errors": []}),
        ):
            result = await usage_controller.limits(_request())

        self.assertEqual(result["timezone"], "America/Los_Angeles")


if __name__ == "__main__":
    unittest.main()
