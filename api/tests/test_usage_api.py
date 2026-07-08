"""Unit tests for api.controller.model_usage — the usage API's time-grammar
conversion and the ID convention (no internal id / user_id in responses).

storage.service.model_usage_daily is mocked; nothing touches a real database.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api.controller import model_usage as usage_controller


def _request(user_id=123):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id))


def _row(**overrides):
    base = {
        "id": 1, "user_id": 123, "usage_date": "2026-07-08", "source": "crs",
        "provider": "anthropic", "model": "claude-opus-4-8", "scope": "aggregate",
        "scope_id": "", "scope_name": "", "input_tokens": 10, "output_tokens": 5,
        "cache_create_tokens": 0, "cache_read_tokens": 0, "all_tokens": 15,
        "requests": 1, "cost": 0.1, "cost_basis": "real", "synced_at": "2026-07-08T00:00:00Z",
    }
    base.update(overrides)
    return SimpleNamespace(to_dict=lambda: dict(base))


class ListModelDailyTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_params_defaults_to_local_today(self):
        with (
            patch.object(usage_controller, "_local_today", return_value="2026-07-08"),
            patch.object(usage_controller.usage_service, "list_for", return_value=[]) as list_for,
        ):
            await usage_controller.list_model_daily(_request(), source="crs", time=None, from_date=None, to_date=None, limit=100000)

        list_for.assert_called_once_with(123, source="crs", from_date="2026-07-08", to_date="2026-07-08", limit=100000)

    async def test_quarter_time_filter_converts_exclusive_end_to_inclusive(self):
        with patch.object(usage_controller.usage_service, "list_for", return_value=[]) as list_for:
            await usage_controller.list_model_daily(_request(), source="crs", time="2024-q2", from_date=None, to_date=None, limit=100000)

        list_for.assert_called_once_with(123, source="crs", from_date="2024-04-01", to_date="2024-06-30", limit=100000)

    async def test_all_time_filter_passes_unbounded_range(self):
        with patch.object(usage_controller.usage_service, "list_for", return_value=[]) as list_for:
            await usage_controller.list_model_daily(_request(), source="crs", time="all", from_date=None, to_date=None, limit=100000)

        list_for.assert_called_once_with(123, source="crs", from_date=None, to_date=None, limit=100000)

    async def test_response_rows_strip_internal_id_and_user_id(self):
        with patch.object(usage_controller.usage_service, "list_for", return_value=[_row()]):
            rows = await usage_controller.list_model_daily(_request(), source="crs", time=None, from_date=None, to_date=None, limit=100000)

        self.assertEqual(len(rows), 1)
        self.assertNotIn("id", rows[0])
        self.assertNotIn("user_id", rows[0])
        self.assertEqual(rows[0]["model"], "claude-opus-4-8")


if __name__ == "__main__":
    unittest.main()
