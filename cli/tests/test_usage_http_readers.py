"""Unit tests for `codex_usage_api` / `xai_billing_credits` (todo 2872
sub-task 3): the response shapes here are LIVE-VERIFIED (2026-07-30 against
a real account) and diverge from the plan's reverse-engineered guesses --
these fixtures are transcribed from the real payloads, not invented.
"""

import base64
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from yagent.commands.usage import _http_readers as hr


def _iso(delta_seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat().replace("+00:00", "Z")


def _jwt(exp_delta_seconds: float) -> str:
    exp = int((datetime.now(timezone.utc) + timedelta(seconds=exp_delta_seconds)).timestamp())
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=").decode()
    return f"header.{payload}.sig"


def _write_codex_auth(path: Path, *, access_expires_in=3600, refresh_token="rt") -> None:
    path.write_text(json.dumps({
        "tokens": {"access_token": _jwt(access_expires_in), "refresh_token": refresh_token},
    }), encoding="utf-8")


def _write_grok_auth(path: Path, *, expires_at=None, refresh_token="rt") -> None:
    path.write_text(json.dumps({
        "issuer::client": {
            "key": "at", "refresh_token": refresh_token,
            "expires_at": expires_at or _iso(3600),
        }
    }), encoding="utf-8")


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

# Transcribed from a live GET https://cli-chat-proxy.grok.com/v1/billing?format=credits
# response (2026-07-30). Kept as the regression case that an explicit
# `creditUsagePercent` is still honoured when present.
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

# Transcribed from a live GET https://cli-chat-proxy.grok.com/v1/billing
# response (no `format` param, 2026-08-03, todo 3001): the plain view no
# longer needs a `format` param for usable numbers -- it carries an explicit
# `used`/`monthlyLimit` ratio and no `creditUsagePercent` at all.
_XAI_LIVE_BODY_PLAIN_2026_08_03 = {
    "config": {
        "monthlyLimit": {"val": 150000},
        "used": {"val": 337},
        "onDemandCap": {"val": 0},
        "billingPeriodStart": "2026-08-01T00:00:00+00:00",
        "billingPeriodEnd": "2026-09-01T00:00:00+00:00",
        "history": [
            {"billingCycle": {"year": 2026, "month": 7},
             "includedUsed": {"val": 0}, "onDemandUsed": {"val": 0}, "totalUsed": {"val": 0}},
        ],
    }
}

# Transcribed from a live GET https://cli-chat-proxy.grok.com/v1/billing?format=credits
# response (2026-08-03, todo 3001): the account's credits view has dropped
# both `creditUsagePercent` and `productUsage` since 2026-07-30.
_XAI_LIVE_BODY_CREDITS_2026_08_03 = {
    "config": {
        "currentPeriod": {
            "type": "USAGE_PERIOD_TYPE_WEEKLY",
            "start": "2026-08-01T17:09:02.794945+00:00",
            "end": "2026-08-08T17:09:02.794945+00:00",
        },
        "onDemandCap": {"val": 0},
        "onDemandUsed": {"val": 0},
        "isUnifiedBillingUser": True,
        "prepaidBalance": {"val": 0},
        "topUpMethod": "TOP_UP_METHOD_SAVED_PAYMENT_METHOD",
        "billingPeriodStart": "2026-08-01T17:09:02.794945+00:00",
        "billingPeriodEnd": "2026-08-08T17:09:02.794945+00:00",
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

    def test_plain_payload_derives_percent_from_used_over_monthly_limit(self):
        window = hr._parse_xai_window(_XAI_LIVE_BODY_PLAIN_2026_08_03)
        self.assertAlmostEqual(window["used_percent"], 337 / 150000 * 100)
        self.assertEqual(window["reset_at"], "2026-09-01T00:00:00Z")
        self.assertEqual(window["extra"], {
            "onDemandCap": 0, "used": 337, "monthlyLimit": 150000,
        })

    def test_explicit_credit_usage_percent_wins_over_derived(self):
        body = {"config": {"creditUsagePercent": 5.0, "used": {"val": 1}, "monthlyLimit": {"val": 100}}}
        window = hr._parse_xai_window(body)
        self.assertEqual(window["used_percent"], 5.0)

    def test_derive_returns_none_without_both_fields(self):
        self.assertIsNone(hr._parse_xai_window({"config": {"used": {"val": 1}}}))
        self.assertIsNone(hr._parse_xai_window({"config": {"monthlyLimit": {"val": 100}}}))

    def test_derive_returns_none_on_zero_or_missing_denominator(self):
        self.assertIsNone(hr._parse_xai_window(
            {"config": {"used": {"val": 1}, "monthlyLimit": {"val": 0}}}))
        self.assertIsNone(hr._parse_xai_window(
            {"config": {"used": {"val": 1}, "monthlyLimit": {"val": None}}}))

    def test_derive_returns_none_on_non_numeric_values(self):
        self.assertIsNone(hr._parse_xai_window(
            {"config": {"used": {"val": "1"}, "monthlyLimit": {"val": 100}}}))
        self.assertIsNone(hr._parse_xai_window(
            {"config": {"used": {"val": True}, "monthlyLimit": {"val": 100}}}))


class ReadCodexProviderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = Path(self._tmp.name) / "codex-auth.json"
        self._path_patch = patch("yagent.commands.usage._credentials.codex_auth_path", return_value=self._path)
        self._path_patch.start()

    def tearDown(self):
        self._path_patch.stop()
        self._tmp.cleanup()

    def test_not_logged_in_when_no_credentials(self):
        row = hr.read_codex_provider()
        self.assertEqual(row["backend"], "codex")
        self.assertEqual(row["provider"], "openai")
        self.assertEqual(row["availability"], "unavailable")
        self.assertEqual(row["error"], "not_logged_in")

    def test_available_row_on_a_good_response(self):
        _write_codex_auth(self._path)
        with patch("yagent.commands.usage._http_readers.httpx.get",
                    return_value=_http_response(200, _CODEX_LIVE_BODY)) as get:
            row = hr.read_codex_provider()

        headers = get.call_args.kwargs["headers"]
        self.assertTrue(headers["Authorization"].startswith("Bearer "))
        self.assertEqual(headers["originator"], "codex_cli_rs")
        self.assertEqual(row["availability"], "available")
        self.assertIsNone(row["error"])
        self.assertIn("one_week", row["windows"])

    def test_401_maps_to_reauth_required(self):
        _write_codex_auth(self._path)
        with patch("yagent.commands.usage._http_readers.httpx.get", return_value=_http_response(401)):
            row = hr.read_codex_provider()
        self.assertEqual(row["availability"], "reauth_required")
        self.assertEqual(row["error"], "reauth_required")

    def test_server_error_maps_to_transport_error(self):
        _write_codex_auth(self._path)
        with patch("yagent.commands.usage._http_readers.httpx.get", return_value=_http_response(500)):
            row = hr.read_codex_provider()
        self.assertEqual(row["error"], "transport_error")

    def test_unrecognized_body_maps_to_parse_failed_not_a_crash(self):
        _write_codex_auth(self._path)
        with patch("yagent.commands.usage._http_readers.httpx.get",
                    return_value=_http_response(200, {"unexpected": "shape"})):
            row = hr.read_codex_provider()
        self.assertEqual(row["error"], "parse_failed")


class ReadXaiProviderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = Path(self._tmp.name) / "grok-auth.json"
        self._path_patch = patch("yagent.commands.usage._credentials.grok_auth_path", return_value=self._path)
        self._path_patch.start()

    def tearDown(self):
        self._path_patch.stop()
        self._tmp.cleanup()

    def test_not_logged_in_when_no_credentials(self):
        row = hr.read_xai_provider()
        self.assertEqual(row["backend"], "grok")
        self.assertEqual(row["provider"], "xai")
        self.assertEqual(row["error"], "not_logged_in")

    def test_available_row_on_a_good_response(self):
        _write_grok_auth(self._path)
        with patch("yagent.commands.usage._http_readers.httpx.get",
                    return_value=_http_response(200, _XAI_LIVE_BODY)) as get:
            row = hr.read_xai_provider()

        headers = get.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer at")
        self.assertIn("x-grok-client-version", headers)
        self.assertEqual(row["availability"], "available")
        self.assertIn("billing_period", row["windows"])

    def test_plain_view_requested_first_and_never_falls_back_when_it_parses(self):
        _write_grok_auth(self._path)
        with patch("yagent.commands.usage._http_readers.httpx.get",
                    return_value=_http_response(200, _XAI_LIVE_BODY_PLAIN_2026_08_03)) as get:
            row = hr.read_xai_provider()

        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], hr.XAI_BILLING_URL)
        self.assertEqual(row["availability"], "available")
        self.assertAlmostEqual(row["windows"]["billing_period"]["used_percent"], 337 / 150000 * 100)

    def test_falls_back_to_credits_view_when_plain_view_has_no_window(self):
        _write_grok_auth(self._path)
        responses = [
            _http_response(200, _XAI_LIVE_BODY_CREDITS_2026_08_03),
            _http_response(200, _XAI_LIVE_BODY),
        ]
        with patch("yagent.commands.usage._http_readers.httpx.get", side_effect=responses) as get:
            row = hr.read_xai_provider()

        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].args[0], hr.XAI_BILLING_URL)
        self.assertEqual(get.call_args_list[1].args[0], hr.XAI_BILLING_CREDITS_URL)
        self.assertEqual(row["availability"], "available")
        self.assertEqual(row["windows"]["billing_period"]["used_percent"], 2.0)

    def test_parse_failed_when_both_views_yield_no_window(self):
        _write_grok_auth(self._path)
        responses = [
            _http_response(200, {"config": {}}),
            _http_response(200, {"config": {}}),
        ]
        with patch("yagent.commands.usage._http_readers.httpx.get", side_effect=responses) as get:
            row = hr.read_xai_provider()

        self.assertEqual(get.call_count, 2)
        self.assertEqual(row["availability"], "unavailable")
        self.assertEqual(row["error"], "parse_failed")
        self.assertEqual(row["windows"], {})


if __name__ == "__main__":
    unittest.main()
