import json

import click

from storage.service import tag as tag_service
from storage.service.user import get_cli_user_id


@click.command("backfill")
@click.option(
    "--type",
    "entity_types",
    multiple=True,
    type=click.Choice(["note", "entity", "todo"]),
    help="Limit to one or more carrier types (default: note+entity+todo)",
)
@click.option("--dry-run", is_flag=True, default=False, help="Count only; do not write entity_tag rows")
@click.option("--limit", type=int, default=None, help="Max items with tags to project per type (for smoke runs)")
@click.option("--user-id", type=int, default=None, help="Internal user id (default: CLI user)")
@click.option("--json", "as_json", is_flag=True, help="Emit the raw result envelope")
def tag_backfill(entity_types, dry_run, limit, user_id, as_json):
    """Project pre-existing note/entity/todo tags into entity_tag.

    Reads authoring surfaces from the DB (note.front_matter.tags,
    entity.front_matter.tags, todo.tags) and reconciles via sync_tags.
    Idempotent: safe to re-run. Scoped to the current CLI user by default.
    """
    target_user_id = user_id or get_cli_user_id()
    types = list(entity_types) if entity_types else None
    result = tag_service.backfill_tags(
        target_user_id,
        dry_run=dry_run,
        entity_types=types,
        limit=limit,
    )
    if as_json:
        click.echo(json.dumps(result, indent=2))
        return
    mode = "dry-run" if result["dry_run"] else "applied"
    click.echo(f"tag backfill ({mode}) user_id={result['user_id']}")
    for entity_type, stats in result["by_type"].items():
        click.echo(
            f"  {entity_type}: scanned={stats['scanned']} with_tags={stats['with_tags']} "
            f"synced={stats['synced']} tag_rows={stats['tag_rows']}"
        )
    click.echo(f"  total: synced={result['total_synced']} tag_rows={result['total_tag_rows']}")
