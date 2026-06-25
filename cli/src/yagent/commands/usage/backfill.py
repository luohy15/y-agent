import json

import click

from storage.service import model_usage_daily as usage_service
from storage.service.user import get_cli_user_id


@click.command("backfill")
@click.option("--source", type=click.Choice(["crs"]), default="crs", help="Backfill source (only crs today)")
@click.option("--days", type=int, default=32, help="Dated daily window depth in days (default 32, the CRS daily-bucket TTL)")
@click.option("--user-id", type=int, default=None, help="Internal user id (default: CLI user)")
@click.option("--json", "as_json", is_flag=True, help="Emit the raw result envelope")
def backfill(source: str, days: int, user_id: int | None, as_json: bool):
    """One-shot historical backfill into model_usage_daily via the CRS admin routes.

    Writes per-day scope='aggregate' rows for [today-days, yesterday] (the recoverable
    ~32-day dated window; older CRS history has expired). Same row shape as the
    go-forward daily sync, idempotent (upsert in place). Needs admin creds
    (CRS_ADMIN_USERNAME/CRS_ADMIN_PASSWORD env or a [crs] config block).
    """
    target_user_id = user_id or get_cli_user_id()
    result = usage_service.backfill_crs(target_user_id, days=days)
    if as_json:
        click.echo(json.dumps(result, indent=2))
        return
    click.echo(f"{result['source']}: {result['status']} (origin {result.get('origin', '')})")
    click.echo(f"  dated days: {len(result.get('days', []))} days, {result.get('daily_rows', 0)} rows")
