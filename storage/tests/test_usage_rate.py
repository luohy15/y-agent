"""Tests for storage.service.usage_rate: direct Relay run-rate reads (todo 3121).

Runs against an isolated in-memory SQLite DB so unittest discover works without
a DATABASE_URL. Covers the closed error envelope, cached-token reuse, and the
401 re-login retry path.
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import storage.database.base as dbbase
import storage.entity.user  # noqa: F401
import storage.entity.user_preference  # noqa: F401
from storage.repository.user import get_or_create_user
from storage.service import model_usage_daily as usage_service
from storage.service import usage_rate
from storage.service import user_preference as user_pref_service


def _future_iso(hours: float = 12) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def _past_iso(hours: float = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def _dashboard(rpm=2.5, tpm=123456, window_minutes=5, is_historical=False):
    return {
        "data": {
            "realtimeMetrics": {
                "rpm": rpm,
                "tpm": tpm,
                "windowMinutes": window_minutes,
                "isHistorical": is_historical,
            }
        }
    }


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://relay.example/admin/dashboard")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


class UsageRateTestCase(unittest.TestCase):
    def setUp(self):
        self._orig_engine = dbbase._engine
        self._orig_session_local = dbbase._SessionLocal

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        dbbase.Base.metadata.create_all(bind=engine)
        dbbase._engine = engine
        dbbase._SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

        self.user_id = get_or_create_user("usage-rate-test").id

    def tearDown(self):
        dbbase._engine = self._orig_engine
        dbbase._SessionLocal = self._orig_session_local


class CredsResolverTest(UsageRateTestCase):
    def test_db_row_wins_over_env(self):
        user_pref_service.upsert_preference(self.user_id, "crs_admin", {
            "username": "db-user",
            "password": "db-pass",
            "session_token": None,
            "token_expires_at": None,
        })
        with patch.dict("os.environ", {
            "CRS_ADMIN_USERNAME": "env-user",
            "CRS_ADMIN_PASSWORD": "env-pass",
        }):
            creds = usage_service._crs_admin_creds(self.user_id)

        self.assertEqual(creds, {"username": "db-user", "password": "db-pass"})

    def test_falls_back_to_env_when_row_absent(self):
        with (
            patch.dict("os.environ", {
                "CRS_ADMIN_USERNAME": "env-user",
                "CRS_ADMIN_PASSWORD": "env-pass",
            }),
            patch.object(usage_service, "_crs_config_block", return_value={}),
        ):
            creds = usage_service._crs_admin_creds(self.user_id)

        self.assertEqual(creds, {"username": "env-user", "password": "env-pass"})

    def test_raises_when_neither_db_nor_env_exists(self):
        with (
            patch.dict("os.environ", {
                "CRS_ADMIN_USERNAME": "",
                "CRS_ADMIN_PASSWORD": "",
            }),
            patch.object(usage_service, "_crs_config_block", return_value={}),
        ):
            with self.assertRaises(RuntimeError):
                usage_service._crs_admin_creds(self.user_id)


class ParseDashboardTest(unittest.TestCase):
    def test_parses_realtime_metrics(self):
        result = usage_rate.parse_dashboard(_dashboard())
        self.assertEqual(result["rpm"], 2.5)
        self.assertEqual(result["tpm"], 123456)
        self.assertEqual(result["window_minutes"], 5)
        self.assertFalse(result["is_historical"])
        self.assertIsNone(result["error"])
        self.assertIsInstance(result["observed_at"], str)

    def test_historical_zero_window_is_allowed(self):
        result = usage_rate.parse_dashboard(_dashboard(window_minutes=0, is_historical=True))
        self.assertEqual(result["window_minutes"], 0)
        self.assertTrue(result["is_historical"])

    def test_malformed_metrics_raise(self):
        with self.assertRaises(ValueError):
            usage_rate.parse_dashboard({"data": {}})
        with self.assertRaises(ValueError):
            usage_rate.parse_dashboard(_dashboard(window_minutes=0, is_historical=False))


class ReadRateTest(UsageRateTestCase):
    def test_missing_credentials_is_not_configured(self):
        with patch(
            "storage.service.usage_rate.usage_service._crs_admin_creds",
            side_effect=RuntimeError("missing"),
        ):
            result = usage_rate.read_rate(self.user_id)

        self.assertEqual(result["error"], "not_configured")
        self.assertIsNone(result["rpm"])
        self.assertEqual(set(result), usage_rate._ENVELOPE_KEYS)

    def test_successful_read_with_fresh_login(self):
        with (
            patch(
                "storage.service.usage_rate.usage_service._crs_admin_creds",
                return_value={"username": "admin", "password": "secret"},
            ),
            patch(
                "storage.service.usage_rate.usage_service._crs_origin",
                return_value="https://relay.example",
            ),
            patch(
                "storage.service.usage_rate.usage_service.crs_admin_login",
                return_value="token-1",
            ) as login,
            patch(
                "storage.service.usage_rate.usage_service.crs_admin_get",
                return_value=_dashboard(),
            ) as get,
        ):
            result = usage_rate.read_rate(self.user_id)

        self.assertIsNone(result["error"])
        self.assertEqual(result["rpm"], 2.5)
        self.assertEqual(result["tpm"], 123456)
        login.assert_called_once_with(
            "https://relay.example", "admin", "secret", timeout=5,
        )
        get.assert_called_once_with(
            "https://relay.example", "/admin/dashboard", "token-1", timeout=5,
        )
        stored = user_pref_service.get_preference(self.user_id, usage_rate.CRS_ADMIN_KEY)
        self.assertEqual(stored.value["session_token"], "token-1")
        self.assertTrue(usage_rate._token_is_current(
            stored.value["session_token"], stored.value["token_expires_at"],
        ))

    def test_cached_token_is_reused_without_login(self):
        user_pref_service.upsert_preference(self.user_id, usage_rate.CRS_ADMIN_KEY, {
            "username": "admin",
            "password": "secret",
            "session_token": "cached-token",
            "token_expires_at": _future_iso(),
        })
        with (
            patch(
                "storage.service.usage_rate.usage_service._crs_admin_creds",
                return_value={"username": "admin", "password": "secret"},
            ),
            patch(
                "storage.service.usage_rate.usage_service._crs_origin",
                return_value="https://relay.example",
            ),
            patch(
                "storage.service.usage_rate.usage_service.crs_admin_login",
            ) as login,
            patch(
                "storage.service.usage_rate.usage_service.crs_admin_get",
                return_value=_dashboard(rpm=4.0),
            ) as get,
        ):
            result = usage_rate.read_rate(self.user_id)

        self.assertIsNone(result["error"])
        self.assertEqual(result["rpm"], 4.0)
        login.assert_not_called()
        get.assert_called_once_with(
            "https://relay.example", "/admin/dashboard", "cached-token", timeout=5,
        )

    def test_expired_token_triggers_login(self):
        user_pref_service.upsert_preference(self.user_id, usage_rate.CRS_ADMIN_KEY, {
            "username": "admin",
            "password": "secret",
            "session_token": "old-token",
            "token_expires_at": _past_iso(),
        })
        with (
            patch(
                "storage.service.usage_rate.usage_service._crs_admin_creds",
                return_value={"username": "admin", "password": "secret"},
            ),
            patch(
                "storage.service.usage_rate.usage_service._crs_origin",
                return_value="https://relay.example",
            ),
            patch(
                "storage.service.usage_rate.usage_service.crs_admin_login",
                return_value="new-token",
            ) as login,
            patch(
                "storage.service.usage_rate.usage_service.crs_admin_get",
                return_value=_dashboard(),
            ) as get,
        ):
            result = usage_rate.read_rate(self.user_id)

        self.assertIsNone(result["error"])
        login.assert_called_once()
        get.assert_called_once_with(
            "https://relay.example", "/admin/dashboard", "new-token", timeout=5,
        )

    def test_dashboard_401_relogs_in_once_and_retries(self):
        user_pref_service.upsert_preference(self.user_id, usage_rate.CRS_ADMIN_KEY, {
            "username": "admin",
            "password": "secret",
            "session_token": "stale-token",
            "token_expires_at": _future_iso(),
        })
        get = Mock(side_effect=[
            _http_error(401),
            _dashboard(rpm=9.0),
        ])
        with (
            patch(
                "storage.service.usage_rate.usage_service._crs_admin_creds",
                return_value={"username": "admin", "password": "secret"},
            ),
            patch(
                "storage.service.usage_rate.usage_service._crs_origin",
                return_value="https://relay.example",
            ),
            patch(
                "storage.service.usage_rate.usage_service.crs_admin_login",
                return_value="fresh-token",
            ) as login,
            patch(
                "storage.service.usage_rate.usage_service.crs_admin_get",
                side_effect=get,
            ),
        ):
            result = usage_rate.read_rate(self.user_id)

        self.assertIsNone(result["error"])
        self.assertEqual(result["rpm"], 9.0)
        login.assert_called_once()
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].args[2], "stale-token")
        self.assertEqual(get.call_args_list[1].args[2], "fresh-token")

    def test_login_401_is_auth_failed(self):
        with (
            patch(
                "storage.service.usage_rate.usage_service._crs_admin_creds",
                return_value={"username": "admin", "password": "wrong"},
            ),
            patch(
                "storage.service.usage_rate.usage_service._crs_origin",
                return_value="https://relay.example",
            ),
            patch(
                "storage.service.usage_rate.usage_service.crs_admin_login",
                side_effect=_http_error(401),
            ),
        ):
            result = usage_rate.read_rate(self.user_id)

        self.assertEqual(result["error"], "auth_failed")
        self.assertIsNone(result["rpm"])

    def test_transport_error_on_non_auth_status(self):
        with (
            patch(
                "storage.service.usage_rate.usage_service._crs_admin_creds",
                return_value={"username": "admin", "password": "secret"},
            ),
            patch(
                "storage.service.usage_rate.usage_service._crs_origin",
                return_value="https://relay.example",
            ),
            patch(
                "storage.service.usage_rate.usage_service.crs_admin_login",
                return_value="token",
            ),
            patch(
                "storage.service.usage_rate.usage_service.crs_admin_get",
                side_effect=_http_error(500),
            ),
        ):
            result = usage_rate.read_rate(self.user_id)

        self.assertEqual(result["error"], "transport_error")

    def test_parse_failed_on_malformed_dashboard(self):
        with (
            patch(
                "storage.service.usage_rate.usage_service._crs_admin_creds",
                return_value={"username": "admin", "password": "secret"},
            ),
            patch(
                "storage.service.usage_rate.usage_service._crs_origin",
                return_value="https://relay.example",
            ),
            patch(
                "storage.service.usage_rate.usage_service.crs_admin_login",
                return_value="token",
            ),
            patch(
                "storage.service.usage_rate.usage_service.crs_admin_get",
                return_value={"data": {}},
            ),
        ):
            result = usage_rate.read_rate(self.user_id)

        self.assertEqual(result["error"], "parse_failed")

    def test_generic_exception_is_transport_error(self):
        with (
            patch(
                "storage.service.usage_rate.usage_service._crs_admin_creds",
                return_value={"username": "admin", "password": "secret"},
            ),
            patch(
                "storage.service.usage_rate.usage_service._crs_origin",
                return_value="https://relay.example",
            ),
            patch(
                "storage.service.usage_rate.usage_service.crs_admin_login",
                side_effect=TimeoutError("hung"),
            ),
        ):
            result = usage_rate.read_rate(self.user_id)

        self.assertEqual(result["error"], "transport_error")


if __name__ == "__main__":
    unittest.main()
