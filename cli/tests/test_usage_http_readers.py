"""Unit tests for `codex_usage_api` / `xai_billing_credits` (todo 2872
sub-task 3): the response shapes here are LIVE-VERIFIED (2026-07-30 against
a real account) and diverge from the plan's reverse-engineered guesses --
these fixtures are transcribed from the real payloads, not invented.
"""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from yagent.commands.usage import _credentials as store
from yagent.commands.usage import _http_readers as hr


def _iso(delta_seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat().replace("+00:00", "Z")


# Transcribed from a live GET https://chatgpt.com/backend-api/codex/usage response.
_CODEX_LIVE_BODY = {
    "user_id": "user-x", "account_id": "acct-x", "email": "x@example.com",
    "plan_type": "pro",
    "rate_limit": {
        "allowed": True, "limit_reached": False,
        "primary_window": {
            "used_percent": 1, "limit_window_seconds": 604800,
            "reset_after_seconds": 481271, "reset_at": 1785902991,
        },
        "secondary_window": None,
    },
    "credits": {"has_credits": False, "unlimited": False, "balance": "0"},
}

# Transcribed from a live GET https://cli-chat-proxy.grok.com/v1/billing?format=credits response.
_XAI_LIVE_BODY = {
    "config": {
        "currentPeriod": {
            "type": "USAGE_PERIOD_TYPE_WEEKLY",
            "start": "2026-07-25T17:09:02.794945+00:00",
            "end": "2026-08-01T17:09:02.794945+00:00",
        },
        "creditUsagePercent": 2.0,
        "onDemandCap": {"val": 0},
        "onDemandUsed": {"val": 0},
        "productUsage": [
            {"product": "GrokBuild", "usagePercent": 1.0},
            {"product": "GrokChat", "usagePercent": 1.0},
        ],
        "isUnifiedBillingUser": True,
        "prepaidBalance": {"val": 0},
        "topUpMethod": "TOP_UP_METHOD_SAVED_PAYMENT_METHOD",
        "billingPeriodStart": "2026-07-25T17:09:02.794945+00:00",
        "billingPeriodEnd": "2026-08-01T17:09:02.794945+00:00",
    }
}


def _http_response(status_code=200, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_body if json_body is not None else {})
    return resp


class ParseCodexWindowsTest(unittest.TestCase):
    def test_live_shape_maps_primary_window_by_seconds_not_position(self):
        windows = hr._parse_codex_windows(_CODEX_LIVE_BODY)
        self.assertEqual(set(windows.keys()), {"one_week"})
        self.assertEqual(windows["one_week"]["used_percent"], 1)
        self.assertEqual(windows["one_week"]["reset_at"], "2026-08-05T04:09:51Z")

    def test_both_windows_populated(self):
        body = {
            "rate_limit": {
                "primary_window": {"used_percent": 10, "limit_window_seconds": 18000, "reset_at": 1000},
                "secondary_window": {"used_percent": 5, "limit_window_seconds": 604800, "reset_at": 2000},
            }
        }
        windows = hr._parse_codex_windows(body)
        self.assertEqual(windows["five_hour"]["used_percent"], 10)
        self.assertEqual(windows["one_week"]["used_percent"], 5)

    def test_unrecognized_window_seconds_is_dropped_not_guessed(self):
        body = {"rate_limit": {"primary_window": {"used_percent": 10, "limit_window_seconds": 999}}}
        self.assertEqual(hr._parse_codex_windows(body), {})

    def test_missing_rate_limit_is_empty(self):
        self.assertEqual(hr._parse_codex_windows({}), {})
        self.assertEqual(hr._parse_codex_windows("not a dict"), {})


class ParseXaiWindowTest(unittest.TestCase):
    def test_live_shape(self):
        window = hr._parse_xai_window(_XAI_LIVE_BODY)
        self.assertEqual(window["used_percent"], 2.0)
        self.assertEqual(window["reset_at"], "2026-08-01T17:09:02.794945Z")
        self.assertEqual(window["extra"], {
            "prepaidBalance": 0, "onDemandCap": 0, "onDemandUsed": 0, "isUnifiedBillingUser": True,
        })

    def test_missing_config_is_none(self):
        self.assertIsNone(hr._parse_xai_window({}))

    def test_missing_credit_usage_percent_is_none(self):
        self.assertIsNone(hr._parse_xai_window({"config": {}}))

    def test_extra_omitted_when_no_documented_fields_present(self):
        window = hr._parse_xai_window({"config": {"creditUsagePercent": 5.0}})
        self.assertNotIn("extra", window)
        self.assertIsNone(window["reset_at"])


class ReadCodexProviderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env_patch = patch.dict(os.environ, {"Y_AGENT_HOME": self._tmp.name})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        self._tmp.cleanup()

    def test_not_logged_in_when_no_credentials(self):
        row = hr.read_codex_provider()
        self.assertEqual(row["backend"], "codex")
        self.assertEqual(row["provider"], "openai")
        self.assertEqual(row["availability"], "unavailable")
        self.assertEqual(row["error"], "not_logged_in")

    def test_available_row_on_a_good_response(self):
        store.set_record("openai", {
            "refresh_token": "rt", "access_token": "at", "expires_at": _iso(3600), "status": "active",
        })
        with patch("yagent.commands.usage._http_readers.httpx.get",
                    return_value=_http_response(200, _CODEX_LIVE_BODY)) as get:
            row = hr.read_codex_provider()

        headers = get.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer at")
        self.assertEqual(headers["originator"], "codex_cli_rs")
        self.assertEqual(row["availability"], "available")
        self.assertIsNone(row["error"])
        self.assertIn("one_week", row["windows"])

    def test_401_maps_to_reauth_required(self):
        store.set_record("openai", {
            "refresh_token": "rt", "access_token": "at", "expires_at": _iso(3600), "status": "active",
        })
        with patch("yagent.commands.usage._http_readers.httpx.get", return_value=_http_response(401)):
            row = hr.read_codex_provider()
        self.assertEqual(row["availability"], "reauth_required")
        self.assertEqual(row["error"], "reauth_required")

    def test_server_error_maps_to_transport_error(self):
        store.set_record("openai", {
            "refresh_token": "rt", "access_token": "at", "expires_at": _iso(3600), "status": "active",
        })
        with patch("yagent.commands.usage._http_readers.httpx.get", return_value=_http_response(500)):
            row = hr.read_codex_provider()
        self.assertEqual(row["error"], "transport_error")

    def test_unrecognized_body_maps_to_parse_failed_not_a_crash(self):
        store.set_record("openai", {
            "refresh_token": "rt", "access_token": "at", "expires_at": _iso(3600), "status": "active",
        })
        with patch("yagent.commands.usage._http_readers.httpx.get",
                    return_value=_http_response(200, {"unexpected": "shape"})):
            row = hr.read_codex_provider()
        self.assertEqual(row["error"], "parse_failed")


class ReadXaiProviderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env_patch = patch.dict(os.environ, {"Y_AGENT_HOME": self._tmp.name})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        self._tmp.cleanup()

    def test_not_logged_in_when_no_credentials(self):
        row = hr.read_xai_provider()
        self.assertEqual(row["backend"], "grok")
        self.assertEqual(row["provider"], "xai")
        self.assertEqual(row["error"], "not_logged_in")

    def test_available_row_on_a_good_response(self):
        store.set_record("xai", {
            "refresh_token": "rt", "access_token": "at", "expires_at": _iso(3600), "status": "active",
        })
        with patch("yagent.commands.usage._http_readers.httpx.get",
                    return_value=_http_response(200, _XAI_LIVE_BODY)) as get:
            row = hr.read_xai_provider()

        headers = get.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer at")
        self.assertIn("x-grok-client-version", headers)
        self.assertEqual(row["availability"], "available")
        self.assertIn("billing_period", row["windows"])


if __name__ == "__main__":
    unittest.main()
