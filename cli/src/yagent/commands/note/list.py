import click

from yagent.api_client import api_request
from yagent.time_filter import collect_time_params, time_filter_options


@click.command("list")
@click.option("--limit", "-l", default=50, help="Max results")
@click.option("--offset", "-o", default=0, help="Offset")
@click.option("--include-deleted", "include_deleted", is_flag=True, default=False, help="Include soft-deleted notes")
@click.option("--tag", default=None, help="Filter by tag (via entity_tag)")
@time_filter_options
def note_list(limit, offset, include_deleted, tag,
              on, from_, to, created_on, created_from, created_to,
              updated_on, updated_from, updated_to):
    """List all notes. Canonical time field: updated_at."""
    params = {"limit": limit, "offset": offset}
    if include_deleted:
        params["include_deleted"] = "true"
    if tag:
        params["tag"] = tag
    params.update(collect_time_params(
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    ))
    resp = api_request("GET", "/api/note/list", params=params)
    notes = resp.json()
    if not notes:
        click.echo("No notes.")
        return
    for n in notes:
        tags = ""
        if n.get("front_matter") and n["front_matter"].get("tags"):
            tags = f" [{', '.join(n['front_matter']['tags'])}]"
        prefix = "[deleted] " if n.get("deleted_at") else ""
        click.echo(f"  {prefix}{n['note_id']}{tags}: {n['content_key']}")
