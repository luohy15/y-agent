"""Tests for agent.usage_limits: the SSH orchestration around `y usage
limits --json` (resolve_vm_config + Tool.run_cmd, mirroring
worker/downloaders/ssh.py), the exact CLI argv (including the `--refresh`
form), the per-user poll-cost TTL memo and its explicit-refresh bypass, the
last-good-as-stale fallback on a transient CLI failure (which must not
clobber a non-available row's own state), and the vm_unreachable state that
never wakes a stopped EC2 instance."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, AsyncMock, patch

from storage.dto.vm import VmConfig

from agent import usage_limits


def _iso(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


def _item(backend="claude_code", provider="anthropic", account_id="acct-1",
          availability="available", error=None, five_hour=42, one_week=18):
    return {
        "backend": backend,
        "provider": provider,
        "account_id": account_id,
        "account_name": "subscription",
        "observed_at": _iso(5),
        "source": f"{provider}_usage",
        "availability": availability,
        "error": error,
        "windows": {
            "five_hour": {"used_percent": five_hour, "reset_at": "2026-07-10T20:00:00Z"} if five_hour is not None else None,
            "one_week": {"used_percent": one_week, "reset_at": "2026-07-15T00:00:00Z"} if one_week is not None else None,
        },
    }


class _UsageLimitsTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        usage_limits._POLL_CACHE.clear()

    def tearDown(self):
        usage_limits._POLL_CACHE.clear()


class CliArgvTest(unittest.IsolatedAsyncioTestCase):
    """Pins the boundary contract to the (not-yet-written) CLI slice: the
    exact argv, including the --refresh form, so it is greppable from both
    sides of the worktree split."""

    async def test_default_argv_has_no_refresh_flag(self):
        vm_config = VmConfig(vm_name="ssh:user@host")
        with patch("agent.tool_base.Tool.run_cmd", AsyncMock(return_value="{}")) as run_cmd:
            await usage_limits._run_usage_limits_cli(vm_config)

        run_cmd.assert_awaited_once_with(["y", "usage", "limits", "--json"], timeout=usage_limits._CLI_TIMEOUT_SECONDS)

    async def test_refresh_appends_the_refresh_flag(self):
        vm_config = VmConfig(vm_name="ssh:user@host")
        with patch("agent.tool_base.Tool.run_cmd", AsyncMock(return_value="{}")) as run_cmd:
            await usage_limits._run_usage_limits_cli(vm_config, refresh=True)

        run_cmd.assert_awaited_once_with(
            ["y", "usage", "limits", "--json", "--refresh"], timeout=usage_limits._CLI_TIMEOUT_SECONDS
        )


class CliFetchTest(_UsageLimitsTestCase):
    async def test_reads_via_resolve_vm_config_and_cli_run_cmd(self):
        vm_config = VmConfig(vm_name="ssh:user@host")
        cli_output = json.dumps({"providers": [_item()], "errors": []})
        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=vm_config) as resolve,
            patch.object(usage_limits, "is_vm_asleep", return_value=False),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock(return_value=cli_output)) as run_cli,
        ):
            result = await usage_limits.get_limit_status(1)

        resolve.assert_called_once_with(1)
        run_cli.assert_awaited_once_with(vm_config, refresh=False)
        self.assertEqual([p["backend"] for p in result["providers"]], ["claude_code"])
        self.assertEqual(result["errors"], [])

    async def test_one_provider_erroring_still_returns_the_other_two(self):
        cli_output = json.dumps({
            "providers": [
                _item(backend="claude_code", provider="anthropic", account_id="acct-claude"),
                _item(backend="codex", provider="openai", account_id="acct-codex"),
            ],
            "errors": [{"origin": "xai", "error": "reauth_required"}],
        })
        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", return_value=False),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock(return_value=cli_output)),
        ):
            result = await usage_limits.get_limit_status(1)

        self.assertEqual(sorted(p["backend"] for p in result["providers"]), ["claude_code", "codex"])
        self.assertEqual(result["errors"], [{"origin": "xai", "error": "reauth_required"}])


class PollCostGuardTest(_UsageLimitsTestCase):
    async def test_burst_of_polls_within_ttl_issues_exactly_one_cli_call(self):
        cli_output = json.dumps({"providers": [_item()], "errors": []})
        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()) as resolve,
            patch.object(usage_limits, "is_vm_asleep", return_value=False),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock(return_value=cli_output)) as run_cli,
        ):
            for _ in range(5):
                await usage_limits.get_limit_status(1)

        run_cli.assert_awaited_once()
        resolve.assert_called_once()

    async def test_different_users_are_cached_independently(self):
        cli_output = json.dumps({"providers": [_item()], "errors": []})
        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", return_value=False),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock(return_value=cli_output)) as run_cli,
        ):
            await usage_limits.get_limit_status(1)
            await usage_limits.get_limit_status(2)

        self.assertEqual(run_cli.await_count, 2)

    async def test_explicit_refresh_bypasses_the_memo_and_the_cli_cache(self):
        """A manual retry must not replay a cached snapshot for up to
        POLL_TTL_SECONDS, and must ask the CLI to bypass its own cache too."""
        cli_output = json.dumps({"providers": [_item()], "errors": []})
        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", return_value=False),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock(return_value=cli_output)) as run_cli,
        ):
            await usage_limits.get_limit_status(1)  # populates the memo
            await usage_limits.get_limit_status(1, refresh=True)  # still inside the TTL

        self.assertEqual(run_cli.await_count, 2)
        run_cli.assert_awaited_with(ANY, refresh=True)

    async def test_transient_cli_failure_serves_last_good_snapshot_as_stale(self):
        cli_output = json.dumps({"providers": [_item(account_id="acct-1", five_hour=42, one_week=18)], "errors": []})
        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", return_value=False),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock(return_value=cli_output)),
        ):
            first = await usage_limits.get_limit_status(1)
        self.assertEqual(first["providers"][0]["freshness"], "fresh")

        # Force the TTL memo to expire so the next call attempts a real read.
        usage_limits._POLL_CACHE[1].fetched_at -= usage_limits.POLL_TTL_SECONDS + 1

        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", return_value=False),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock(side_effect=RuntimeError("ssh timeout"))),
        ):
            second = await usage_limits.get_limit_status(1)

        self.assertEqual(len(second["providers"]), 1)
        self.assertEqual(second["providers"][0]["account_id"], "acct-1")
        self.assertEqual(second["providers"][0]["windows"]["five_hour"]["used_percent"], 42)
        self.assertEqual(second["providers"][0]["freshness"], "stale")
        self.assertEqual(second["providers"][0]["error"], "cli_failed")
        self.assertEqual(second["errors"], [{"origin": "vm", "error": "cli_failed"}])

    async def test_transient_cli_failure_does_not_clobber_a_non_available_row(self):
        """A reauth_required row already carries the freshness _freshness
        requires (unavailable) and its own actionable error code; a transport
        blip on the *next* poll must leave it completely alone rather than
        overwriting it to freshness=stale (which would violate the
        non-available-implies-unavailable-freshness invariant and make
        BotViewer render a blank card instead of the reauth-required one)."""
        cli_output = json.dumps({
            "providers": [_item(
                account_id="acct-1", availability="reauth_required", error="invalid_grant",
                five_hour=None, one_week=None,
            )],
            "errors": [],
        })
        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", return_value=False),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock(return_value=cli_output)),
        ):
            first = await usage_limits.get_limit_status(1)
        self.assertEqual(first["providers"][0]["availability"], "reauth_required")
        self.assertEqual(first["providers"][0]["freshness"], "unavailable")

        usage_limits._POLL_CACHE[1].fetched_at -= usage_limits.POLL_TTL_SECONDS + 1

        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", return_value=False),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock(side_effect=RuntimeError("connection reset"))),
        ):
            second = await usage_limits.get_limit_status(1)

        self.assertEqual(second["providers"][0]["availability"], "reauth_required")
        self.assertEqual(second["providers"][0]["freshness"], "unavailable")
        self.assertEqual(second["providers"][0]["error"], "invalid_grant")

    async def test_cli_failure_with_no_prior_snapshot_returns_empty_providers_with_error(self):
        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", return_value=False),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock(side_effect=RuntimeError("ssh timeout"))),
        ):
            result = await usage_limits.get_limit_status(1)

        self.assertEqual(result["providers"], [])
        self.assertEqual(result["errors"], [{"origin": "vm", "error": "cli_failed"}])

    async def test_bad_json_maps_to_bad_payload_not_raw_exception_text(self):
        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", return_value=False),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock(return_value="not json")),
        ):
            result = await usage_limits.get_limit_status(1)

        self.assertEqual(result["errors"], [{"origin": "vm", "error": "bad_payload"}])

    async def test_valid_json_wrong_shape_does_not_clobber_last_good_and_serves_stale(self):
        """A bad_payload envelope (valid JSON, missing the providers key) must
        degrade the same way a JSONDecodeError-flavoured bad_payload already
        does: serve the last-good snapshot as stale, not overwrite last_good
        with an empty providers list. Otherwise the same error code behaves
        oppositely depending on which failure mode produced it, and a later
        transient failure would blank a card that still has real data."""
        cli_output = json.dumps({"providers": [_item(account_id="acct-1", five_hour=42, one_week=18)], "errors": []})
        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", return_value=False),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock(return_value=cli_output)),
        ):
            first = await usage_limits.get_limit_status(1)
        self.assertEqual(first["providers"][0]["freshness"], "fresh")

        usage_limits._POLL_CACHE[1].fetched_at -= usage_limits.POLL_TTL_SECONDS + 1

        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", return_value=False),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock(return_value=json.dumps({"error": "not logged in"}))),
        ):
            second = await usage_limits.get_limit_status(1)

        self.assertEqual(len(second["providers"]), 1)
        self.assertEqual(second["providers"][0]["account_id"], "acct-1")
        self.assertEqual(second["providers"][0]["windows"]["five_hour"]["used_percent"], 42)
        self.assertEqual(second["providers"][0]["freshness"], "stale")
        self.assertEqual(second["providers"][0]["error"], "bad_payload")

        # A subsequent transient failure must still see the real snapshot,
        # proving the wrong-shape read above did not get promoted to last_good.
        usage_limits._POLL_CACHE[1].fetched_at -= usage_limits.POLL_TTL_SECONDS + 1
        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", return_value=False),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock(side_effect=RuntimeError("timeout"))),
        ):
            third = await usage_limits.get_limit_status(1)

        self.assertEqual(len(third["providers"]), 1)
        self.assertEqual(third["providers"][0]["windows"]["five_hour"]["used_percent"], 42)

    async def test_bad_payload_with_no_prior_snapshot_returns_empty_providers(self):
        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", return_value=False),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock(return_value=json.dumps({"error": "not logged in"}))),
        ):
            result = await usage_limits.get_limit_status(1)

        self.assertEqual(result["providers"], [])
        self.assertEqual(result["errors"], [{"origin": "vm", "error": "bad_payload"}])


class ControlPlaneFailureTest(_UsageLimitsTestCase):
    """resolve_vm_config / is_vm_asleep must degrade the same way a failed
    SSH read does, not raise out of get_limit_status and 500 a 60s-polled
    endpoint."""

    async def test_resolve_vm_config_failure_degrades_instead_of_raising(self):
        with (
            patch.object(usage_limits, "resolve_vm_config", side_effect=RuntimeError("db unavailable")),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock()) as run_cli,
        ):
            result = await usage_limits.get_limit_status(1)

        run_cli.assert_not_called()
        self.assertEqual(result["providers"], [])
        self.assertEqual(result["errors"], [{"origin": "vm", "error": "cli_failed"}])

    async def test_is_vm_asleep_failure_degrades_instead_of_raising(self):
        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", side_effect=RuntimeError("RequestLimitExceeded")),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock()) as run_cli,
        ):
            result = await usage_limits.get_limit_status(1)

        run_cli.assert_not_called()
        self.assertEqual(result["providers"], [])
        self.assertEqual(result["errors"], [{"origin": "vm", "error": "cli_failed"}])


class VmUnreachableTest(_UsageLimitsTestCase):
    async def test_stopped_vm_never_calls_the_cli_and_reports_vm_unreachable(self):
        cli_output = json.dumps({"providers": [_item(account_id="acct-1")], "errors": []})
        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", return_value=False),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock(return_value=cli_output)),
        ):
            await usage_limits.get_limit_status(1)
        usage_limits._POLL_CACHE[1].fetched_at -= usage_limits.POLL_TTL_SECONDS + 1

        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", return_value=True),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock()) as run_cli,
        ):
            result = await usage_limits.get_limit_status(1)

        run_cli.assert_not_called()
        self.assertEqual(len(result["providers"]), 1)
        self.assertEqual(result["providers"][0]["availability"], "unavailable")
        self.assertEqual(result["providers"][0]["error"], "vm_unreachable")
        self.assertEqual(result["errors"], [{"origin": "vm", "error": "vm_unreachable"}])

    async def test_stopped_vm_with_no_prior_snapshot_returns_empty_providers(self):
        with (
            patch.object(usage_limits, "resolve_vm_config", return_value=VmConfig()),
            patch.object(usage_limits, "is_vm_asleep", return_value=True),
            patch.object(usage_limits, "_run_usage_limits_cli", AsyncMock()) as run_cli,
        ):
            result = await usage_limits.get_limit_status(1)

        run_cli.assert_not_called()
        self.assertEqual(result["providers"], [])
        self.assertEqual(result["errors"], [{"origin": "vm", "error": "vm_unreachable"}])


if __name__ == "__main__":
    unittest.main()
