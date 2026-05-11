import click

from yagent.api_client import api_request


@click.command("list")
@click.option("--limit", "-l", default=50, help="Max results")
@click.option("--offset", "-o", default=0, help="Offset")
@click.option("--include-deleted", "include_deleted", is_flag=True, default=False, help="Include soft-deleted notes")
def note_list(limit, offset, include_deleted):
    """List all notes."""
    params = {"limit": limit, "offset": offset}
    if include_deleted:
        params["include_deleted"] = "true"
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
