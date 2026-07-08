"""Sync contract + repository upsert-shape tests for
storage.service.model_usage_daily / storage.repository.model_usage_daily.

Covers the PRD Testing Decisions items that aren't fava time-grammar:
  - shared (origin, api_key) keys are queried exactly once (dedup)
  - per-model sums across distinct keys
  - one failing key aborts the whole sync (nothing upserted)
  - _derive_provider vendor mapping
  - repo `_values` normalization + on_conflict `set_` covers every mutable column
"""

import unittest
from unittest.mock import patch

from sqlalchemy import Column

from storage.dto.bot import BotConfig
from storage.entity.base import BaseEntity
from storage.entity.model_usage_daily import ModelUsageDailyEntity
from storage.repository import model_usage_daily as repo
from storage.service import model_usage_daily as usage_service


def _bot(name, api_key, base_url="https://cc1.yovy.app/api"):
    return BotConfig(name=name, api_key=api_key, base_url=base_url)


class CrsTargetsDedupTest(unittest.TestCase):
    def test_shared_key_across_bots_deduped_to_one_target(self):
        bots = [_bot("claude_code", "cr_shared"), _bot("codex", "cr_shared")]
        with patch.object(usage_service.bot_config_service, "list_configs", return_value=bots):
            targets = usage_service._crs_targets(1)
        self.assertEqual(targets, [("https://cc1.yovy.app", "cr_shared")])

    def test_distinct_keys_and_origins_kept_separate(self):
        bots = [
            _bot("a", "cr_one", base_url="https://cc1.yovy.app/api"),
            _bot("b", "cr_two", base_url="https://cc2.yovy.app/api"),
        ]
        with patch.object(usage_service.bot_config_service, "list_configs", return_value=bots):
            targets = usage_service._crs_targets(1)
        self.assertEqual(
            targets,
            [("https://cc1.yovy.app", "cr_one"), ("https://cc2.yovy.app", "cr_two")],
        )

    def test_non_cr_keys_ignored(self):
        bots = [_bot("openrouter", "sk-or-abc")]
        with patch.object(usage_service.bot_config_service, "list_configs", return_value=bots):
            targets = usage_service._crs_targets(1)
        self.assertEqual(targets, [])


class SyncCrsTest(unittest.TestCase):
    def test_shared_key_fetched_once(self):
        bots = [_bot("claude_code", "cr_shared"), _bot("codex", "cr_shared")]
        fetch = self._fetch_returning({("https://cc1.yovy.app", "cr_shared"): [
            {"model": "claude-opus-4-8", "inputTokens": 10, "outputTokens": 5, "allTokens": 15, "requests": 1, "costs": {"real": 0.1}},
        ]})
        with (
            patch.object(usage_service.bot_config_service, "list_configs", return_value=bots),
            patch.object(usage_service, "_fetch_crs_key", side_effect=fetch) as fetch_mock,
            patch.object(usage_service, "upsert_daily", return_value=1) as upsert,
        ):
            result = usage_service.sync_crs(1, synced_at="2026-07-08T00:00:00Z")

        fetch_mock.assert_called_once_with("https://cc1.yovy.app", "cr_shared")
        self.assertEqual(result["status"], "ok")
        upsert.assert_called_once()

    def test_per_model_sums_across_distinct_keys(self):
        bots = [
            _bot("a", "cr_one", base_url="https://cc1.yovy.app/api"),
            _bot("b", "cr_two", base_url="https://cc2.yovy.app/api"),
        ]
        fetch = self._fetch_returning({
            ("https://cc1.yovy.app", "cr_one"): [
                {"model": "claude-opus-4-8", "inputTokens": 10, "outputTokens": 5, "allTokens": 15, "requests": 1, "costs": {"real": 0.1}},
            ],
            ("https://cc2.yovy.app", "cr_two"): [
                {"model": "claude-opus-4-8", "inputTokens": 20, "outputTokens": 8, "allTokens": 28, "requests": 2, "costs": {"real": 0.2}},
                {"model": "gpt-5.5", "inputTokens": 1, "outputTokens": 1, "allTokens": 2, "requests": 1, "costs": {"real": 0.05}},
            ],
        })
        captured = {}

        def fake_upsert(user_id, rows, synced_at=None):
            captured["rows"] = rows
            return len(rows)

        with (
            patch.object(usage_service.bot_config_service, "list_configs", return_value=bots),
            patch.object(usage_service, "_fetch_crs_key", side_effect=fetch),
            patch.object(usage_service, "upsert_daily", side_effect=fake_upsert),
        ):
            result = usage_service.sync_crs(1, synced_at="2026-07-08T00:00:00Z")

        self.assertEqual(result["status"], "ok")
        by_model = {r["model"]: r for r in captured["rows"]}
        self.assertEqual(by_model["claude-opus-4-8"]["input_tokens"], 30)
        self.assertEqual(by_model["claude-opus-4-8"]["output_tokens"], 13)
        self.assertEqual(by_model["claude-opus-4-8"]["all_tokens"], 43)
        self.assertEqual(by_model["claude-opus-4-8"]["requests"], 3)
        self.assertAlmostEqual(by_model["claude-opus-4-8"]["cost"], 0.3)
        self.assertEqual(by_model["gpt-5.5"]["all_tokens"], 2)

    def test_one_failing_key_aborts_with_nothing_upserted(self):
        bots = [
            _bot("a", "cr_one", base_url="https://cc1.yovy.app/api"),
            _bot("b", "cr_two", base_url="https://cc2.yovy.app/api"),
        ]

        def fetch(origin, api_key):
            if api_key == "cr_two":
                raise RuntimeError("boom")
            return [{"model": "claude-opus-4-8", "inputTokens": 10, "outputTokens": 5, "allTokens": 15, "requests": 1, "costs": {"real": 0.1}}]

        with (
            patch.object(usage_service.bot_config_service, "list_configs", return_value=bots),
            patch.object(usage_service, "_fetch_crs_key", side_effect=fetch),
            patch.object(usage_service, "upsert_daily") as upsert,
        ):
            result = usage_service.sync_crs(1, synced_at="2026-07-08T00:00:00Z")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["rows"], 0)
        upsert.assert_not_called()

    def test_no_targets_is_skip(self):
        with patch.object(usage_service.bot_config_service, "list_configs", return_value=[]):
            result = usage_service.sync_crs(1)
        self.assertEqual(result["status"], "skip")

    @staticmethod
    def _fetch_returning(by_target):
        def fetch(origin, api_key):
            return by_target[(origin, api_key)]
        return fetch


class DeriveProviderTest(unittest.TestCase):
    def test_bare_model_prefixes_map_to_vendor(self):
        cases = {
            "claude-opus-4-8": "anthropic",
            "gpt-5.5": "openai",
            "o3-mini": "openai",
            "chatgpt-4o": "openai",
            "gemini-2.5-pro": "google",
            "grok-4": "x-ai",
            "glm-4.6": "z-ai",
            "deepseek-v3": "deepseek",
            "qwen3-max": "qwen",
            "kimi-k2": "moonshotai",
            "moonshot-v1": "moonshotai",
            "minimax-m2": "minimax",
        }
        for model, expected in cases.items():
            self.assertEqual(usage_service._derive_provider(model), expected, model)

    def test_vendor_slash_model_id_uses_vendor_prefix(self):
        self.assertEqual(usage_service._derive_provider("anthropic/claude-opus-4-8"), "anthropic")
        self.assertEqual(usage_service._derive_provider("openai/gpt-5.5"), "openai")

    def test_unknown_or_wildcard_model_maps_to_empty(self):
        self.assertEqual(usage_service._derive_provider("*"), "")
        self.assertEqual(usage_service._derive_provider(""), "")
        self.assertEqual(usage_service._derive_provider("some-unknown-model"), "")


class UpsertValuesNormalizationTest(unittest.TestCase):
    def test_values_normalizes_missing_fields_to_defaults(self):
        row = {"source": "crs", "usage_date": "2026-07-08"}
        values = repo._values(1, row, synced_at="2026-07-08T00:00:00Z")
        self.assertEqual(values["provider"], "")
        self.assertEqual(values["model"], "*")
        self.assertEqual(values["scope"], "aggregate")
        self.assertEqual(values["scope_id"], "")
        self.assertEqual(values["input_tokens"], 0)
        self.assertEqual(values["cost"], 0.0)
        self.assertEqual(values["cost_basis"], "real")

    def test_values_coerces_numeric_types(self):
        row = {
            "source": "crs", "usage_date": "2026-07-08", "model": "claude-opus-4-8",
            "input_tokens": "10", "cost": "1.5",
        }
        values = repo._values(1, row, synced_at="2026-07-08T00:00:00Z")
        self.assertEqual(values["input_tokens"], 10)
        self.assertIsInstance(values["input_tokens"], int)
        self.assertEqual(values["cost"], 1.5)
        self.assertIsInstance(values["cost"], float)


class UpsertOnConflictSetCoversAllMutableColumnsTest(unittest.TestCase):
    def test_on_conflict_set_covers_every_column_outside_the_unique_key(self):
        """Guards the 'add a column, forget the upsert set' failure: every entity
        column that isn't part of the unique key (user_id, usage_date, source,
        scope_id, model) or the synced_at/updated_at pair set unconditionally
        must appear in the ON CONFLICT SET clause, otherwise a re-sync silently
        keeps a stale value for that column."""
        # Domain-specific columns (excludes BaseEntity's audit columns like
        # created_at, which aren't part of this table's explicit mutable-set
        # contract) minus "id" and the unique-key columns.
        base_audit_columns = {k for k, v in BaseEntity.__dict__.items() if isinstance(v, Column)}
        all_columns = {c.name for c in ModelUsageDailyEntity.__table__.columns}
        domain_columns = all_columns - base_audit_columns - {"id"}
        unique_key_columns = {"user_id", "usage_date", "source", "scope_id", "model"}
        expected_settable = domain_columns - unique_key_columns
        # `updated_at` is inherited from BaseEntity but is explicitly stamped
        # and included in the ON CONFLICT set by the repo.
        always_set_columns = {"updated_at"}

        with patch.object(repo, "insert") as insert_mock, patch.object(repo, "get_db"):
            stmt = insert_mock.return_value.values.return_value
            repo.upsert_daily(
                1,
                [{"source": "crs", "usage_date": "2026-07-08", "model": "claude-opus-4-8"}],
                synced_at="2026-07-08T00:00:00Z",
            )

        _, kwargs = stmt.on_conflict_do_update.call_args
        self.assertEqual(kwargs["constraint"], "uq_model_usage_daily")
        actual_set_keys = set(kwargs["set_"].keys())
        self.assertEqual(actual_set_keys, expected_settable | always_set_columns)


if __name__ == "__main__":
    unittest.main()
