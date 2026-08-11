"""Direct CRS run-rate reader shared by the API and CLI.

The Relay admin credentials and its reusable session token live in the caller's
``user_preference`` row. Reads call Relay directly, with no VM, cron job, or
stored rate snapshot on the path.
"""

from datetime import datetime, timedelta, timezone
import math

import httpx
from loguru import logger

from storage.service import model_usage_daily as usage_service
from storage.service import user_preference as user_pref_service
from storage.util import get_utc_iso8601_timestamp

CRS_ADMIN_KEY = "crs_admin"
_TOKEN_TTL = timedelta(hours=23)
_ENVELOPE_KEYS = {"rpm", "tpm", "window_minutes", "is_historical", "observed_at", "error"}

_ERROR_NOT_CONFIGURED = "not_configured"
_ERROR_AUTH_FAILED = "auth_failed"
_ERROR_TRANSPORT = "transport_error"
_ERROR_PARSE = "parse_failed"


def _envelope(*, rpm=None, tpm=None, window_minutes=None, is_historical=None, error=None) -> dict:
    return {
        "rpm": rpm,
        "tpm": tpm,
        "window_minutes": window_minutes,
        "is_historical": is_historical,
        "observed_at": get_utc_iso8601_timestamp(),
        "error": error,
    }


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def parse_dashboard(data: dict) -> dict:
    """Parse Relay's dashboard response into the public rate envelope."""
    metrics = data.get("data", {}).get("realtimeMetrics") if isinstance(data, dict) else None
    if not isinstance(metrics, dict):
        raise ValueError("missing realtimeMetrics")

    rpm = _number(metrics.get("rpm"))
    tpm = _number(metrics.get("tpm"))
    window_minutes = _number(metrics.get("windowMinutes"))
    is_historical = metrics.get("isHistorical")
    if (
        rpm is None or tpm is None or window_minutes is None or window_minutes < 0
        or not isinstance(is_historical, bool)
        or (window_minutes == 0 and not is_historical)
    ):
        raise ValueError("malformed realtimeMetrics")
    return _envelope(
        rpm=rpm,
        tpm=tpm,
        window_minutes=window_minutes,
        is_historical=is_historical,
    )


def _token_is_current(token: object, expires_at: object) -> bool:
    if not isinstance(token, str) or not token or not isinstance(expires_at, str):
        return False
    try:
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return expires.tzinfo is not None and expires > datetime.now(timezone.utc)


def _save_token(user_id: int, creds: dict, token: str) -> None:
    user_pref_service.upsert_preference(user_id, CRS_ADMIN_KEY, {
        "username": creds["username"],
        "password": creds["password"],
        "session_token": token,
        "token_expires_at": (datetime.now(timezone.utc) + _TOKEN_TTL).isoformat().replace("+00:00", "Z"),
    })


def _login(user_id: int, origin: str, creds: dict) -> str:
    try:
        token = usage_service.crs_admin_login(origin, creds["username"], creds["password"], timeout=5)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            raise PermissionError from exc
        raise
    _save_token(user_id, creds, token)
    return token


def read_rate(user_id: int) -> dict:
    """Read current Relay RPM/TPM directly with a cached admin session token."""
    try:
        creds = usage_service._crs_admin_creds(user_id)
    except RuntimeError:
        return _envelope(error=_ERROR_NOT_CONFIGURED)

    origin = usage_service._crs_origin(user_id)
    pref = user_pref_service.get_preference(user_id, CRS_ADMIN_KEY)
    stored = pref.value if pref and isinstance(pref.value, dict) else {}
    token = stored.get("session_token") if _token_is_current(stored.get("session_token"), stored.get("token_expires_at")) else None

    try:
        token = token or _login(user_id, origin, creds)
        try:
            dashboard = usage_service.crs_admin_get(origin, "/admin/dashboard", token, timeout=5)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 401:
                raise
            token = _login(user_id, origin, creds)
            dashboard = usage_service.crs_admin_get(origin, "/admin/dashboard", token, timeout=5)
        return parse_dashboard(dashboard)
    except PermissionError:
        return _envelope(error=_ERROR_AUTH_FAILED)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            return _envelope(error=_ERROR_AUTH_FAILED)
        logger.warning("usage_rate.read_rate: Relay returned {} for user {}", exc.response.status_code, user_id)
        return _envelope(error=_ERROR_TRANSPORT)
    except ValueError:
        return _envelope(error=_ERROR_PARSE)
    except Exception:
        logger.warning("usage_rate.read_rate: Relay request failed for user {}", user_id)
        return _envelope(error=_ERROR_TRANSPORT)
