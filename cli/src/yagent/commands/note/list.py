import click

from yagent.api_client import api_request


@click.command("list")
@click.option("--limit", "-l", default=50, help="Max results")
@click.option("--offset", "-o", default=0, help="Offset")
def note_list(limit, offset):
    """List all notes."""
    resp = api_request("GET", "/api/note/list", params={"limit": limit, "offset": offset})
    notes = resp.json()
    if not notes:
        click.echo("No notes.")
        return
    for n in notes:
        tags = ""
        if n.get("front_matter") and n["front_matter"].get("tags"):
            tags = f" [{', '.join(n['front_matter']['tags'])}]"
        click.echo(f"  {n['note_id']}{tags}: {n['content_key']}")
