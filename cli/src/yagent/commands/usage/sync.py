import json

import click

from storage.service import model_usage_daily as usage_service
from storage.service.user import get_cli_user_id


@click.command("sync")
@click.option("--source", type=click.Choice(["crs", "agy"]), default=None, help="Limit to one source (default: all)")
@click.option("--user-id", type=int, default=None, help="Internal user id (default: CLI user)")
@click.option("--json", "as_json", is_flag=True, help="Emit the raw result envelope")
def sync(source: str | None, user_id: int | None, as_json: bool):
    """Pull daily + hourly LLM token/cost usage (idempotent upsert).

    The envelope carries one result per grain: source='crs' (daily),
    source='crs-hourly' (hourly over yesterday+today), and source='agy' (the
    non-relay recompute, which also runs without a relay credential).
    """
    target_user_id = user_id or get_cli_user_id()
    result = usage_service.sync(target_user_id, source=source)
    if as_json:
        click.echo(json.dumps(result, indent=2))
        return
    results = result.get("results") or []
    for r in results:
        line = f"{r['source']}: {r['status']} ({r.get('rows', 0)} rows)"
        reason = r.get("reason")
        if reason:
            line += f" - {reason}"
        dates = r.get("dates")
        if dates:
            line += f" dates={','.join(dates)}"
        click.echo(line)
    # The envelope carries a reason the per-result lines cannot: a missing
    # relay credential on a source=None run (agy still produced a result), or
    # a source=crs run with no results at all. Never drop it silently.
    reason = result.get("reason")
    if reason:
        click.echo(f"{result.get('status', 'unknown')}: {reason}")
    elif not results:
        click.echo(f"{result.get('status', 'unknown')}: no sources")
