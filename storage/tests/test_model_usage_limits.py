"""Contract tests for storage.service.model_usage_limits.

Covers the PRD Testing Decisions for subscription limit-window status:
  - distinct relay-key (target) enumeration is reused, not duplicated
  - one target's failure is isolated to `errors`, the rest still succeeds
  - relay-key/account candidates collapse to one best row per backend
  - stale vs fresh vs unavailable is derived from observed_at + TTL, not
    from a merely-successful CRS probe
  - missing/malformed values stay null, never coerced to 0
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from storage.dto.bot import BotConfig
from storage.service import model_usage_daily
from storage.service import model_usage_limits as limits_service


def _bot(name, api_key, base_url="https://cc1.yovy.app/api"):
    return BotConfig(name=name, api_key=api_key, base_url=base_url)


def _iso(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


def _account(backend="claude_code", provider="anthropic", account_id="acct-1",
             observed_at=None, availability="available", used_5h=42, used_1w=18):
    return {
        "backend": backend,
        "provider": provider,
        "account_id": account_id,
        "account_name": "Claude subscription",
        "observed_at": observed_at if observed_at is not None else _iso(5),
        "source": "anthropic_oauth_usage",
        "availability": availability,
        "error": None,
        "windows": {
            "five_hour": {"used_percent": used_5h, "reset_at": "2026-07-10T20:00:00Z"} if used_5h is not None else None,
            "one_week": {"used_percent": used_1w, "reset_at": "2026-07-15T00:00:00Z"} if used_1w is not None else None,
        },
    }


class GetLimitStatusTargetEnumerationTest(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_the_daily_sync_target_enumeration(self):
        bots = [_bot("claude_code", "cr_shared"), _bot("codex", "cr_shared")]
        with (
            patch.object(model_usage_daily.bot_config_service, "list_configs", return_value=bots),
            patch.object(limits_service, "_fetch_crs_limits", return_value=[]) as fetch,
        ):
            result = await limits_service.get_limit_status(1)

        fetch.assert_called_once_with("https://cc1.yovy.app", "cr_shared")
        self.assertEqual(result, {"providers": [], "errors": []})

    async def test_no_targets_returns_empty_envelope(self):
        with patch.object(model_usage_daily.bot_config_service, "list_configs", return_value=[]):
            result = await limits_service.get_limit_status(1)
        self.assertEqual(result, {"providers": [], "errors": []})


class GetLimitStatusPartialFailureTest(unittest.IsolatedAsyncioTestCase):
    async def test_one_origin_failure_does_not_block_the_other(self):
        bots = [
            _bot("a", "cr_one", base_url="https://cc1.yovy.app/api"),
            _bot("b", "cr_two", base_url="https://cc2.yovy.app/api"),
        ]

        async def fetch(origin, api_key):
            if origin == "https://cc2.yovy.app":
                raise RuntimeError("timeout")
            return [_account(account_id="acct-1")]

        with (
            patch.object(model_usage_daily.bot_config_service, "list_configs", return_value=bots),
            patch.object(limits_service, "_fetch_crs_limits", side_effect=fetch),
        ):
            result = await limits_service.get_limit_status(1)

        self.assertEqual(len(result["providers"]), 1)
        self.assertEqual(result["providers"][0]["account_id"], "acct-1")
        self.assertEqual(result["errors"], [{"origin": "https://cc2.yovy.app", "error": "timeout"}])


class GetLimitStatusDeduplicationTest(unittest.IsolatedAsyncioTestCase):
    async def test_same_account_from_multiple_targets_is_deduplicated(self):
        bots = [
            _bot("a", "cr_one", base_url="https://cc1.yovy.app/api"),
            _bot("b", "cr_two", base_url="https://cc1.yovy.app/api"),
        ]

        async def fetch(origin, api_key):
            return [_account(account_id="acct-shared")]

        with (
            patch.object(model_usage_daily.bot_config_service, "list_configs", return_value=bots),
            patch.object(limits_service, "_fetch_crs_limits", side_effect=fetch),
        ):
            result = await limits_service.get_limit_status(1)

        self.assertEqual(len(result["providers"]), 1)

    async def test_available_dedicated_account_beats_no_stable_scope_from_another_key(self):
        bots = [
            _bot("a", "cr_old", base_url="https://cc1.yovy.app/api"),
            _bot("b", "cr_bound", base_url="https://cc1.yovy.app/api"),
        ]

        async def fetch(origin, api_key):
            if api_key == "cr_old":
                return [_account(
                    account_id=None,
                    availability="unavailable",
                    used_5h=None,
                    used_1w=None,
                ) | {"error": "no_stable_account_scope"}]
            return [_account(account_id="acct-bound", observed_at=_iso(5))]

        with (
            patch.object(model_usage_daily.bot_config_service, "list_configs", return_value=bots),
            patch.object(limits_service, "_fetch_crs_limits", side_effect=fetch),
        ):
            result = await limits_service.get_limit_status(1)

        self.assertEqual(len(result["providers"]), 1)
        self.assertEqual(result["providers"][0]["account_id"], "acct-bound")
        self.assertEqual(result["providers"][0]["freshness"], "fresh")

    async def test_fresh_candidate_beats_stale_candidate_across_relay_keys(self):
        bots = [
            _bot("a", "cr_stale", base_url="https://cc1.yovy.app/api"),
            _bot("b", "cr_fresh", base_url="https://cc2.yovy.app/api"),
        ]

        async def fetch(origin, api_key):
            return [_account(
                account_id=f"acct-{api_key}",
                observed_at=_iso(600 if api_key == "cr_stale" else 5),
            )]

        with (
            patch.object(model_usage_daily.bot_config_service, "list_configs", return_value=bots),
            patch.object(limits_service, "_fetch_crs_limits", side_effect=fetch),
        ):
            result = await limits_service.get_limit_status(1)

        self.assertEqual(len(result["providers"]), 1)
        self.assertEqual(result["providers"][0]["account_id"], "acct-cr_fresh")

    async def test_same_freshness_uses_newest_observation(self):
        bots = [
            _bot("a", "cr_z", base_url="https://cc1.yovy.app/api"),
            _bot("b", "cr_a", base_url="https://cc2.yovy.app/api"),
        ]
        older = _iso(30)
        newer = _iso(5)

        async def fetch(origin, api_key):
            return [_account(
                account_id="acct-z" if api_key == "cr_z" else "acct-a",
                observed_at=older if api_key == "cr_z" else newer,
            )]

        with (
            patch.object(model_usage_daily.bot_config_service, "list_configs", return_value=bots),
            patch.object(limits_service, "_fetch_crs_limits", side_effect=fetch),
        ):
            result = await limits_service.get_limit_status(1)

        self.assertEqual(result["providers"][0]["account_id"], "acct-a")

    async def test_exact_tie_uses_stable_identity_and_origin_tie_breaks(self):
        bots = [
            _bot("a", "cr_z", base_url="https://cc2.yovy.app/api"),
            _bot("b", "cr_a", base_url="https://cc1.yovy.app/api"),
        ]
        observed_at = "2026-07-10T08:00:00Z"

        async def fetch(origin, api_key):
            return [_account(
                account_id="acct-z" if api_key == "cr_z" else "acct-a",
                observed_at=observed_at,
            )]

        with (
            patch.object(model_usage_daily.bot_config_service, "list_configs", return_value=bots),
            patch.object(limits_service, "_fetch_crs_limits", side_effect=fetch),
        ):
            result = await limits_service.get_limit_status(1, ttl_seconds=10**9)

        self.assertEqual(result["providers"][0]["account_id"], "acct-a")

    async def test_boundary_collision_tie_break_is_independent_of_target_order(self):
        observed_at = "2026-07-10T08:00:00Z"

        async def fetch(origin, api_key):
            if api_key == "cr_one":
                return [_account(account_id="a", observed_at=observed_at) | {"account_name": "bc"}]
            return [_account(account_id="ab", observed_at=observed_at) | {"account_name": "c"}]

        async def selected_account(bots):
            with (
                patch.object(model_usage_daily.bot_config_service, "list_configs", return_value=bots),
                patch.object(limits_service, "_fetch_crs_limits", side_effect=fetch),
            ):
                result = await limits_service.get_limit_status(1, ttl_seconds=10**9)
            return result["providers"][0]["account_id"]

        forward = await selected_account([
            _bot("a", "cr_one", base_url="https://cc1.yovy.app/api"),
            _bot("b", "cr_two", base_url="https://cc2.yovy.app/api"),
        ])
        reversed_order = await selected_account([
            _bot("b", "cr_two", base_url="https://cc2.yovy.app/api"),
            _bot("a", "cr_one", base_url="https://cc1.yovy.app/api"),
        ])

        self.assertEqual(forward, "ab")
        self.assertEqual(reversed_order, forward)

    async def test_one_unavailable_candidate_is_retained_when_no_usable_candidate_exists(self):
        bots = [
            _bot("a", "cr_one", base_url="https://cc1.yovy.app/api"),
            _bot("b", "cr_two", base_url="https://cc2.yovy.app/api"),
        ]

        async def fetch(origin, api_key):
            return [_account(
                account_id=None,
                availability="unavailable",
                used_5h=None,
                used_1w=None,
            ) | {"error": "no_stable_account_scope"}]

        with (
            patch.object(model_usage_daily.bot_config_service, "list_configs", return_value=bots),
            patch.object(limits_service, "_fetch_crs_limits", side_effect=fetch),
        ):
            result = await limits_service.get_limit_status(1)

        self.assertEqual(len(result["providers"]), 1)
        self.assertEqual(result["providers"][0]["freshness"], "unavailable")
        self.assertEqual(result["providers"][0]["error"], "no_stable_account_scope")

    async def test_one_card_per_backend_across_multiple_accounts_and_keys(self):
        async def fetch(origin, api_key):
            return [
                _account(backend="claude_code", account_id=f"acct-claude-{api_key}"),
                _account(backend="codex", provider="openai", account_id=f"acct-codex-{api_key}"),
            ]

        bots = [
            _bot("claude_code", "cr_one", base_url="https://cc1.yovy.app/api"),
            _bot("codex", "cr_two", base_url="https://cc2.yovy.app/api"),
        ]
        with (
            patch.object(model_usage_daily.bot_config_service, "list_configs", return_value=bots),
            patch.object(limits_service, "_fetch_crs_limits", side_effect=fetch),
        ):
            result = await limits_service.get_limit_status(1)

        self.assertEqual([p["backend"] for p in result["providers"]], ["claude_code", "codex"])
        self.assertEqual(len(result["providers"]), 2)
        self.assertEqual([p["account_id"] for p in result["providers"]], ["acct-claude-cr_two", "acct-codex-cr_two"])


class NormalizeAccountTest(unittest.TestCase):
    def test_remaining_percent_derived_from_used_percent(self):
        item = _account(used_5h=42, used_1w=18)
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["windows"]["five_hour"]["remaining_percent"], 58)
        self.assertEqual(row["windows"]["one_week"]["remaining_percent"], 82)

    def test_missing_used_percent_stays_null_not_zero(self):
        item = _account(used_5h=None, used_1w=18)
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertIsNone(row["windows"]["five_hour"])
        self.assertEqual(row["windows"]["one_week"]["used_percent"], 18)

    def test_malformed_used_percent_yields_null_used_and_remaining(self):
        item = _account()
        item["windows"]["five_hour"]["used_percent"] = "not-a-number"
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertIsNone(row["windows"]["five_hour"]["used_percent"])
        self.assertIsNone(row["windows"]["five_hour"]["remaining_percent"])

    def test_non_finite_used_percent_yields_null(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            item = _account()
            item["windows"]["five_hour"]["used_percent"] = bad
            row = limits_service._normalize_account(item, ttl_seconds=300)
            self.assertIsNone(row["windows"]["five_hour"]["used_percent"], bad)
            self.assertIsNone(row["windows"]["five_hour"]["remaining_percent"], bad)

    def test_extra_windows_preserved_without_displacing_required(self):
        item = _account()
        item["extra_windows"] = {"one_week_sonnet": {"used_percent": 8, "reset_at": "2026-07-15T00:00:00Z"}}
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["extra_windows"]["one_week_sonnet"]["used_percent"], 8)
        self.assertIn("five_hour", row["windows"])
        self.assertIn("one_week", row["windows"])


class FreshnessTest(unittest.TestCase):
    def test_recent_observation_is_fresh(self):
        item = _account(observed_at=_iso(5))
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["freshness"], "fresh")

    def test_old_observation_beyond_ttl_is_stale(self):
        item = _account(observed_at=_iso(600))
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["freshness"], "stale")

    def test_unavailable_availability_is_unavailable_regardless_of_age(self):
        item = _account(availability="unavailable", observed_at=_iso(5), used_5h=None, used_1w=None)
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["freshness"], "unavailable")

    def test_missing_observed_at_is_unavailable(self):
        item = _account(observed_at=None)
        item["observed_at"] = None
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["freshness"], "unavailable")

    def test_no_required_window_data_is_unavailable_even_if_recently_observed(self):
        item = _account(observed_at=_iso(5), used_5h=None, used_1w=None)
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["freshness"], "unavailable")

    def test_all_windows_malformed_is_unavailable_never_fresh(self):
        """Regression: malformed used_percent must never count as a real,
        current window, even though a recent observed_at and 'available'
        source status are both present."""
        item = _account(observed_at=_iso(5), availability="available")
        item["windows"]["five_hour"]["used_percent"] = "not-a-number"
        item["windows"]["one_week"]["used_percent"] = float("nan")
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertIsNone(row["windows"]["five_hour"]["used_percent"])
        self.assertIsNone(row["windows"]["one_week"]["used_percent"])
        self.assertEqual(row["freshness"], "unavailable")


class GetLimitStatusMalformedItemTest(unittest.IsolatedAsyncioTestCase):
    async def test_non_dict_item_is_isolated_and_valid_items_still_return(self):
        async def fetch(origin, api_key):
            return ["not-a-dict-item", _account(account_id="acct-valid")]

        bots = [_bot("claude_code", "cr_one")]
        with (
            patch.object(model_usage_daily.bot_config_service, "list_configs", return_value=bots),
            patch.object(limits_service, "_fetch_crs_limits", side_effect=fetch),
        ):
            result = await limits_service.get_limit_status(1)

        self.assertEqual(len(result["providers"]), 1)
        self.assertEqual(result["providers"][0]["account_id"], "acct-valid")
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["origin"], "https://cc1.yovy.app")

    async def test_malformed_windows_shape_is_isolated_and_other_origin_still_returns(self):
        async def fetch(origin, api_key):
            if origin == "https://cc1.yovy.app":
                item = _account(account_id="acct-bad")
                item["windows"] = "not-a-dict"
                return [item]
            return [_account(account_id="acct-good")]

        bots = [
            _bot("a", "cr_one", base_url="https://cc1.yovy.app/api"),
            _bot("b", "cr_two", base_url="https://cc2.yovy.app/api"),
        ]
        with (
            patch.object(model_usage_daily.bot_config_service, "list_configs", return_value=bots),
            patch.object(limits_service, "_fetch_crs_limits", side_effect=fetch),
        ):
            result = await limits_service.get_limit_status(1)

        self.assertEqual(len(result["providers"]), 1)
        self.assertEqual(result["providers"][0]["account_id"], "acct-good")
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["origin"], "https://cc1.yovy.app")


if __name__ == "__main__":
    unittest.main()
