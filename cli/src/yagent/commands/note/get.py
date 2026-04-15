import json

import click

from yagent.api_client import api_request


@click.command("get")
@click.argument("note_id")
def note_get(note_id):
    """Get note details."""
    resp = api_request("GET", "/api/note/detail", params={"note_id": note_id})
    note = resp.json()
    click.echo(f"ID:          {note['note_id']}")
    click.echo(f"Content Key: {note['content_key']}")
    if note.get("front_matter"):
        click.echo(f"Front Matter: {json.dumps(note['front_matter'])}")
    if note.get("created_at"):
        click.echo(f"Created:     {note['created_at']}")
    if note.get("updated_at"):
        click.echo(f"Updated:     {note['updated_at']}")
