"""Contract tests for storage.service.model_usage_limits: pure normalization,
freshness, and candidate-ranking logic over per-provider payload fixtures
(the raw shape `y usage limits --json` emits). The SSH orchestration /
poll-cost-guard / vm_unreachable behavior lives in agent.usage_limits (storage
must not depend on agent) and is covered by agent/tests/test_usage_limits.py.

Covers the PRD Testing Decisions for subscription limit-window status:
  - stale vs fresh vs unavailable is derived from observed_at + TTL, not
    from a merely-successful read
  - missing/malformed values stay null, never coerced to 0
  - any populated window (not just five_hour/one_week) makes a row usable,
    so a Grok-only billing_period row is not permanently unavailable
  - a dead grant reports availability="reauth_required"
  - candidates collapse to one best row per backend
  - one malformed item is isolated into `errors` without discarding the rest
"""

import unittest
from datetime import datetime, timedelta, timezone

from storage.service import model_usage_limits as limits_service


def _iso(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


def _item(backend="claude_code", provider="anthropic", account_id="acct-1",
          account_name="subscription", observed_at=None, availability="available", error=None,
          five_hour=42, one_week=18, billing_period=None):
    windows = {}
    if five_hour is not None:
        windows["five_hour"] = {"used_percent": five_hour, "reset_at": "2026-07-10T20:00:00Z"}
    if one_week is not None:
        windows["one_week"] = {"used_percent": one_week, "reset_at": "2026-07-15T00:00:00Z"}
    if billing_period is not None:
        windows["billing_period"] = {"used_percent": billing_period, "reset_at": "2026-08-01T00:00:00Z"}
    return {
        "backend": backend,
        "provider": provider,
        "account_id": account_id,
        "account_name": account_name,
        "observed_at": observed_at if observed_at is not None else _iso(5),
        "source": f"{provider}_usage",
        "availability": availability,
        "error": error,
        "windows": windows,
    }


class NormalizeAccountTest(unittest.TestCase):
    def test_remaining_percent_derived_from_used_percent(self):
        item = _item(five_hour=42, one_week=18)
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["windows"]["five_hour"]["remaining_percent"], 58)
        self.assertEqual(row["windows"]["one_week"]["remaining_percent"], 82)

    def test_missing_used_percent_stays_null_not_zero(self):
        item = _item(five_hour=None, one_week=18)
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertIsNone(row["windows"]["five_hour"])
        self.assertEqual(row["windows"]["one_week"]["used_percent"], 18)

    def test_malformed_used_percent_yields_null_used_and_remaining(self):
        item = _item()
        item["windows"]["five_hour"]["used_percent"] = "not-a-number"
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertIsNone(row["windows"]["five_hour"]["used_percent"])
        self.assertIsNone(row["windows"]["five_hour"]["remaining_percent"])

    def test_non_finite_used_percent_yields_null(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            item = _item()
            item["windows"]["five_hour"]["used_percent"] = bad
            row = limits_service._normalize_account(item, ttl_seconds=300)
            self.assertIsNone(row["windows"]["five_hour"]["used_percent"], bad)
            self.assertIsNone(row["windows"]["five_hour"]["remaining_percent"], bad)

    def test_extra_windows_preserved_without_displacing_required(self):
        item = _item()
        item["extra_windows"] = {"one_week_sonnet": {"used_percent": 8, "reset_at": "2026-07-15T00:00:00Z"}}
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["extra_windows"]["one_week_sonnet"]["used_percent"], 8)
        self.assertIn("five_hour", row["windows"])
        self.assertIn("one_week", row["windows"])

    def test_billing_period_window_is_first_class_not_extra(self):
        item = _item(provider="xai", backend="grok", five_hour=None, one_week=None, billing_period=63)
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["windows"]["billing_period"]["used_percent"], 63)
        self.assertEqual(row["windows"]["billing_period"]["remaining_percent"], 37)
        self.assertIsNone(row["windows"]["five_hour"])
        self.assertIsNone(row["windows"]["one_week"])

    def test_reauth_required_availability_is_preserved(self):
        item = _item(availability="reauth_required", five_hour=None, one_week=None, error="invalid_grant")
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["availability"], "reauth_required")
        self.assertEqual(row["error"], "invalid_grant")


class FreshnessTest(unittest.TestCase):
    def test_recent_observation_is_fresh(self):
        item = _item(observed_at=_iso(5))
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["freshness"], "fresh")

    def test_old_observation_beyond_ttl_is_stale(self):
        item = _item(observed_at=_iso(600))
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["freshness"], "stale")

    def test_unavailable_availability_is_unavailable_regardless_of_age(self):
        item = _item(availability="unavailable", observed_at=_iso(5), five_hour=None, one_week=None)
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["freshness"], "unavailable")

    def test_reauth_required_availability_is_unavailable_freshness(self):
        item = _item(availability="reauth_required", observed_at=_iso(5), five_hour=None, one_week=None)
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["freshness"], "unavailable")

    def test_missing_observed_at_is_unavailable(self):
        item = _item(observed_at=None)
        item["observed_at"] = None
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["freshness"], "unavailable")

    def test_no_required_window_data_is_unavailable_even_if_recently_observed(self):
        item = _item(observed_at=_iso(5), five_hour=None, one_week=None)
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["freshness"], "unavailable")

    def test_all_windows_malformed_is_unavailable_never_fresh(self):
        """Regression: malformed used_percent must never count as a real,
        current window, even though a recent observed_at and 'available'
        source status are both present."""
        item = _item(observed_at=_iso(5), availability="available")
        item["windows"]["five_hour"]["used_percent"] = "not-a-number"
        item["windows"]["one_week"]["used_percent"] = float("nan")
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertIsNone(row["windows"]["five_hour"]["used_percent"])
        self.assertIsNone(row["windows"]["one_week"]["used_percent"])
        self.assertEqual(row["freshness"], "unavailable")

    def test_grok_only_billing_period_row_is_available_and_fresh(self):
        """A provider that only ever reports a billing_period window (Grok)
        must not be permanently unavailable for lacking five_hour/one_week."""
        item = _item(
            provider="xai", backend="grok", account_id="acct-grok",
            observed_at=_iso(5), availability="available",
            five_hour=None, one_week=None, billing_period=12,
        )
        row = limits_service._normalize_account(item, ttl_seconds=300)
        self.assertEqual(row["availability"], "available")
        self.assertEqual(row["freshness"], "fresh")


class NormalizeEnvelopeTest(unittest.TestCase):
    def test_one_card_per_backend_and_fresh_beats_stale(self):
        raw = {
            "providers": [
                _item(backend="claude_code", account_id="stale", observed_at=_iso(600)),
                _item(backend="claude_code", account_id="fresh", observed_at=_iso(5)),
                _item(backend="codex", provider="openai", account_id="acct-codex"),
            ],
            "errors": [],
        }
        result = limits_service.normalize_envelope(raw)
        self.assertEqual(
            sorted(p["backend"] for p in result["providers"]),
            ["claude_code", "codex"],
        )
        claude = next(p for p in result["providers"] if p["backend"] == "claude_code")
        self.assertEqual(claude["account_id"], "fresh")

    def test_one_provider_erroring_still_returns_the_other_two(self):
        raw = {
            "providers": [
                _item(backend="claude_code", provider="anthropic", account_id="acct-claude"),
                _item(backend="codex", provider="openai", account_id="acct-codex"),
            ],
            "errors": [{"origin": "xai", "error": "reauth_required"}],
        }
        result = limits_service.normalize_envelope(raw)
        self.assertEqual(
            sorted(p["backend"] for p in result["providers"]),
            ["claude_code", "codex"],
        )
        self.assertEqual(result["errors"], [{"origin": "xai", "error": "reauth_required"}])

    def test_malformed_item_is_isolated_and_valid_items_still_return(self):
        raw = {"providers": ["not-a-dict-item", _item(account_id="acct-valid")], "errors": []}
        result = limits_service.normalize_envelope(raw)
        self.assertEqual(len(result["providers"]), 1)
        self.assertEqual(result["providers"][0]["account_id"], "acct-valid")
        self.assertEqual(len(result["errors"]), 1)

    def test_empty_providers_returns_empty_envelope(self):
        result = limits_service.normalize_envelope({"providers": [], "errors": []})
        self.assertEqual(result, {"providers": [], "errors": []})

    def test_missing_providers_key_is_a_malformed_payload_not_silently_empty(self):
        """A well-formed-JSON-wrong-shape payload (e.g. a producer emitting
        {"error": "not logged in"} on a bad login) must surface as an error,
        not collapse into an envelope indistinguishable from "unconfigured"."""
        result = limits_service.normalize_envelope({"error": "not logged in"})
        self.assertEqual(result["providers"], [])
        self.assertEqual(result["errors"], [{"origin": "vm", "error": "bad_payload"}])

    def test_non_dict_payload_is_a_malformed_payload(self):
        result = limits_service.normalize_envelope(["not", "a", "dict"])
        self.assertEqual(result["providers"], [])
        self.assertEqual(result["errors"], [{"origin": "vm", "error": "bad_payload"}])

    def test_origin_is_parameterized_not_hardcoded(self):
        result = limits_service.normalize_envelope({"error": "nope"}, origin="test-origin")
        self.assertEqual(result["errors"], [{"origin": "test-origin", "error": "bad_payload"}])


class CandidateRankTest(unittest.TestCase):
    """_candidate_rank survives verbatim from the CRS era; these cases are
    observation-recency / lexical-tie-break behavior, not relay-key specific,
    so they are restored here against normalize_envelope's single-origin
    input rather than dropped with the relay-key dedup cases."""

    def test_same_freshness_uses_newest_observation(self):
        older = _iso(30)
        newer = _iso(5)
        raw = {
            "providers": [
                _item(backend="claude_code", account_id="acct-z", observed_at=older),
                _item(backend="claude_code", account_id="acct-a", observed_at=newer),
            ],
            "errors": [],
        }
        result = limits_service.normalize_envelope(raw)
        self.assertEqual(result["providers"][0]["account_id"], "acct-a")

    def test_exact_tie_uses_stable_identity(self):
        observed_at = "2026-07-10T08:00:00Z"
        raw = {
            "providers": [
                _item(backend="claude_code", account_id="acct-z", observed_at=observed_at),
                _item(backend="claude_code", account_id="acct-a", observed_at=observed_at),
            ],
            "errors": [],
        }
        result = limits_service.normalize_envelope(raw, ttl_seconds=10**9)
        self.assertEqual(result["providers"][0]["account_id"], "acct-a")

    def test_tie_break_is_independent_of_item_order(self):
        observed_at = "2026-07-10T08:00:00Z"

        def selected(order):
            result = limits_service.normalize_envelope({"providers": order, "errors": []}, ttl_seconds=10**9)
            return result["providers"][0]["account_id"]

        a = _item(backend="claude_code", account_id="a", account_name="bc", observed_at=observed_at)
        ab = _item(backend="claude_code", account_id="ab", account_name="c", observed_at=observed_at)

        forward = selected([a, ab])
        reversed_order = selected([ab, a])

        self.assertEqual(forward, "ab")
        self.assertEqual(reversed_order, forward)

    def test_one_unavailable_candidate_is_retained_when_no_usable_candidate_exists(self):
        """This is what makes a reauth_required (or otherwise dead) card
        render at all instead of vanishing when there is nothing usable."""
        raw = {
            "providers": [
                _item(
                    backend="claude_code", account_id=None, availability="unavailable",
                    five_hour=None, one_week=None, error="no_stable_account_scope",
                )
            ],
            "errors": [],
        }
        result = limits_service.normalize_envelope(raw)
        self.assertEqual(len(result["providers"]), 1)
        self.assertEqual(result["providers"][0]["freshness"], "unavailable")
        self.assertEqual(result["providers"][0]["error"], "no_stable_account_scope")


if __name__ == "__main__":
    unittest.main()
