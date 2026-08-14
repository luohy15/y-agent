import json

import click

from storage.service import model_usage_daily as usage_service
from storage.service import model_usage_hourly as hourly_service
from storage.service.user import get_cli_user_id


@click.command("backfill")
@click.option("--source", type=click.Choice(["crs"]), default="crs", help="Backfill source (only crs today)")
@click.option("--days", type=int, default=32, help="Dated daily window depth in days (default 32, the CRS daily-bucket TTL)")
@click.option(
    "--hourly-days",
    type=int,
    default=None,
    help="Also backfill hourly for the last N local days (capped at 7, the CRS hourly TTL). Omit to skip hourly.",
)
@click.option("--user-id", type=int, default=None, help="Internal user id (default: CLI user)")
@click.option("--json", "as_json", is_flag=True, help="Emit the raw result envelope")
def backfill(source: str, days: int, hourly_days: int | None, user_id: int | None, as_json: bool):
    """One-shot historical backfill into model_usage_daily (and optionally hourly).

    Daily: writes per-day scope='aggregate' rows for [today-days, yesterday] via
    the CRS admin routes (the recoverable ~32-day dated window). Hourly: when
    --hourly-days N is set (N capped at 7), replays the per-key hourly path for
    the last N local days including today.
    """
    target_user_id = user_id or get_cli_user_id()
    result = usage_service.backfill_crs(target_user_id, days=days)
    if hourly_days is not None:
        result["hourly"] = hourly_service.backfill_crs_hourly(
            target_user_id, days=hourly_days,
        )
    if as_json:
        click.echo(json.dumps(result, indent=2))
        return
    click.echo(f"{result['source']}: {result['status']} (origin {result.get('origin', '')})")
    click.echo(f"  dated days: {len(result.get('days', []))} days, {result.get('daily_rows', 0)} rows")
    hourly = result.get("hourly")
    if hourly:
        click.echo(
            f"  hourly: {hourly.get('status')} ({hourly.get('rows', 0)} rows, "
            f"{hourly.get('hourly_days', 0)} days)"
        )
