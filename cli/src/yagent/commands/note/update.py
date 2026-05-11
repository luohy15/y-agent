import os

import click

from yagent.api_client import api_request
from .import_note import _compute_content_key


@click.command("update")
@click.argument("note_id")
@click.option("--content-key", "content_key", help="New content_key (absolute path or path under ~/luohy15/)")
def note_update(note_id, content_key):
    """Update a note's content_key (typically after a file rename)."""
    if content_key is None:
        click.echo("Nothing to update. Pass --content-key <path>.", err=True)
        raise click.Abort()

    if os.path.isabs(content_key) or os.path.exists(content_key):
        resolved = _compute_content_key(content_key)
    else:
        resolved = content_key

    resp = api_request("POST", "/api/note/update", json={"note_id": note_id, "content_key": resolved})
    note = resp.json()
    click.echo(f"Updated note {note['note_id']}: content_key = {note['content_key']}")
