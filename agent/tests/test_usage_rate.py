import json
import unittest
from unittest.mock import AsyncMock, patch

from storage.dto.vm import VmConfig

from agent import usage_rate


def _good():
    return {
        "rpm": 2.5,
        "tpm": 123456,
        "window_minutes": 5,
        "is_historical": False,
        "observed_at": "2026-08-10T00:00:00Z",
        "error": None,
    }


class UsageRateTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        usage_rate._POLL_CACHE.clear()

    def tearDown(self):
        usage_rate._POLL_CACHE.clear()

    async def test_fresh_rate_uses_vm_cli(self):
        vm_config = VmConfig()
        with (
            patch.object(usage_rate, "resolve_vm_config", return_value=vm_config),
            patch.object(usage_rate, "is_vm_asleep", return_value=False),
            patch.object(usage_rate, "_run_usage_rate_cli", AsyncMock(return_value=json.dumps(_good()))) as run_cli,
        ):
            result = await usage_rate.get_usage_rate(1)

        self.assertEqual(result, _good())
        run_cli.assert_awaited_once_with(vm_config)

    async def test_historical_zero_minute_window_reaches_callers(self):
        historical = {**_good(), "window_minutes": 0, "is_historical": True}
        with (
            patch.object(usage_rate, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_rate, "is_vm_asleep", return_value=False),
            patch.object(usage_rate, "_run_usage_rate_cli", AsyncMock(return_value=json.dumps(historical))),
        ):
            result = await usage_rate.get_usage_rate(1)

        self.assertEqual(result, historical)

    async def test_vm_asleep_short_circuits_without_cli(self):
        with (
            patch.object(usage_rate, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_rate, "is_vm_asleep", return_value=True),
            patch.object(usage_rate, "_run_usage_rate_cli", AsyncMock()) as run_cli,
        ):
            result = await usage_rate.get_usage_rate(1)

        run_cli.assert_not_called()
        self.assertEqual(result["error"], "vm_unreachable")
        self.assertIsNone(result["rpm"])

    async def test_transient_failure_retains_last_good_value_with_stale_error(self):
        with (
            patch.object(usage_rate, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_rate, "is_vm_asleep", return_value=False),
            patch.object(usage_rate, "_run_usage_rate_cli", AsyncMock(return_value=json.dumps(_good()))),
        ):
            await usage_rate.get_usage_rate(1)
        usage_rate._POLL_CACHE[1].fetched_at -= usage_rate.POLL_TTL_SECONDS + 1

        with (
            patch.object(usage_rate, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_rate, "is_vm_asleep", return_value=False),
            patch.object(usage_rate, "_run_usage_rate_cli", AsyncMock(side_effect=RuntimeError("private host timeout"))),
        ):
            result = await usage_rate.get_usage_rate(1)

        self.assertEqual(result["rpm"], 2.5)
        self.assertEqual(result["error"], "cli_failed")
        self.assertTrue(result["stale"])
        self.assertNotIn("private host", json.dumps(result))

    async def test_bad_payload_returns_closed_error_without_exception_text(self):
        with (
            patch.object(usage_rate, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_rate, "is_vm_asleep", return_value=False),
            patch.object(usage_rate, "_run_usage_rate_cli", AsyncMock(return_value=json.dumps({"rpm": 2.5}))),
        ):
            result = await usage_rate.get_usage_rate(1)

        self.assertEqual(result["error"], "bad_payload")
        self.assertNotIn("unexpected", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
