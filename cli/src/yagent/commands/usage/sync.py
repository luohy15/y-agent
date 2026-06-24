import json

import click

from storage.service import model_usage_daily as usage_service
from storage.service.user import get_cli_user_id


@click.command("sync")
@click.option("--source", type=click.Choice(["crs"]), default=None, help="Limit to one source (default: all)")
@click.option("--user-id", type=int, default=None, help="Internal user id (default: CLI user)")
@click.option("--json", "as_json", is_flag=True, help="Emit the raw result envelope")
def sync(source: str | None, user_id: int | None, as_json: bool):
    """Pull daily LLM token/cost usage into model_usage_daily (idempotent upsert)."""
    target_user_id = user_id or get_cli_user_id()
    result = usage_service.sync(target_user_id, source=source)
    if as_json:
        click.echo(json.dumps(result, indent=2))
        return
    for r in result["results"]:
        line = f"{r['source']}: {r['status']} ({r.get('rows', 0)} rows)"
        reason = r.get("reason")
        if reason:
            line += f" - {reason}"
        click.echo(line)
