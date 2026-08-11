"""`y usage rate [--json] [--store]`: the CRS dashboard's current 5-minute RPM/TPM.

The CRS admin session and HTTP request run only on the user's VM. `--store`
persists the reading via `storage.service.usage_rate` so `GET /api/usage/rate`
can read it from the database instead of running this CLI per request; a
per-minute VM crontab (`scripts/usage-rate-store.sh`) is the only intended
caller of `--store` (see docs/prd/bot-usage.md "Realtime run rate").
"""

import json
import math

import click

from storage.service import model_usage_daily as usage_service
from storage.service import usage_rate as rate_storage
from storage.service.user import get_cli_user_id
from storage.util import get_utc_iso8601_timestamp


_ERROR_NOT_CONFIGURED = "not_configured"
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


def _parse_dashboard(data: dict) -> dict:
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


@click.command("rate")
@click.option("--json", "as_json", is_flag=True, help="Output the raw JSON envelope")
@click.option(
    "--store", is_flag=True,
    help="Persist this reading to user_preference for GET /api/usage/rate to read (VM cron only)",
)
def rate(as_json: bool, store: bool):
    """Read the current CRS RPM/TPM dashboard metrics."""
    user_id = get_cli_user_id()
    try:
        username, password = usage_service._crs_admin_creds()
    except RuntimeError:
        result = _envelope(error=_ERROR_NOT_CONFIGURED)
    else:
        try:
            origin = usage_service._crs_origin(user_id)
            token = usage_service.crs_admin_login(origin, username, password)
            result = _parse_dashboard(usage_service.crs_admin_get(origin, "/admin/dashboard", token))
        except ValueError:
            result = _envelope(error=_ERROR_PARSE)
        except Exception:
            result = _envelope(error=_ERROR_TRANSPORT)

    if store:
        rate_storage.store_reading(user_id, result)

    if as_json:
        click.echo(json.dumps(result))
        return
    if result["error"]:
        click.echo(f"CRS run rate unavailable: {result['error']}", err=True)
        return
    historical = " (historical)" if result["is_historical"] else ""
    click.echo(f"{result['rpm']:.1f} RPM  {result['tpm']:.1f} TPM over {result['window_minutes']} minutes{historical}")
