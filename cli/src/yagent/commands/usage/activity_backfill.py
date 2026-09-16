import json

import click

from storage.service import chat_model_activity as activity_service
from storage.service.user import get_cli_user_id


@click.command("backfill-activity")
@click.option("--days", type=click.IntRange(min=1), required=True, help="Inclusive local-day window ending today")
@click.option("--user-id", type=int, default=None, help="Internal user id (default: CLI user)")
@click.option("--json", "as_json", is_flag=True, help="Emit the raw result envelope")
def backfill_activity(days: int, user_id: int | None, as_json: bool):
    """Rebuild y-agent chat session and answered-turn activity for N days."""
    target_user_id = user_id or get_cli_user_id()
    result = activity_service.backfill_days(target_user_id, days)
    if as_json:
        click.echo(json.dumps(result, indent=2))
        return
    click.echo(
        f"chat activity: {result['status']} "
        f"({result['from_date']} to {result['to_date']}, "
        f"{result['chats']} chats, {result['rows']} rows)"
    )
