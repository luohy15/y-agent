"""`y usage rate [--json]`: current CRS dashboard RPM/TPM."""

import json

import click

from storage.service import model_usage_daily as usage_service
from storage.service import usage_rate as rate_service
from storage.service.user import get_cli_user_id
from storage.util import get_utc_iso8601_timestamp


def _not_configured() -> dict:
    return {
        "rpm": None,
        "tpm": None,
        "window_minutes": None,
        "is_historical": None,
        "observed_at": get_utc_iso8601_timestamp(),
        "error": "not_configured",
    }


@click.command("rate")
@click.option("--json", "as_json", is_flag=True, help="Output the raw JSON envelope")
def rate(as_json: bool):
    """Read the current CRS RPM/TPM dashboard metrics."""
    # Resolve credentials before requiring a CLI database user so a bare CI
    # environment (no DATABASE_URL / Y_USER_ID / CRS creds) still returns the
    # closed not_configured envelope instead of exit 1 (todo 3121 / cfe596d).
    try:
        usage_service._crs_admin_creds()
        has_local_creds = True
    except RuntimeError:
        has_local_creds = False

    try:
        user_id = get_cli_user_id()
    except Exception:
        if has_local_creds:
            raise
        result = _not_configured()
    else:
        result = rate_service.read_rate(user_id)

    if as_json:
        click.echo(json.dumps(result))
        return
    if result["error"]:
        click.echo(f"CRS run rate unavailable: {result['error']}", err=True)
        return
    historical = " (historical)" if result["is_historical"] else ""
    click.echo(f"{result['rpm']:.1f} RPM  {result['tpm']:.1f} TPM over {result['window_minutes']} minutes{historical}")
