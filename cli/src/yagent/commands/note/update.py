import click

from yagent.api_client import api_request
from .import_note import _compute_content_key, _parse_front_matter, resolve_content_path


@click.command("update")
@click.argument("note_id")
@click.option("--content-key", "content_key", help="New content_key (absolute or relative to $Y_AGENT_HOME)")
@click.option("--front-matter", "front_matter", is_flag=True, help="Re-read YAML front matter from the file at content_key")
def note_update(note_id, content_key, front_matter):
    """Update a note's content_key and/or front matter (typically after a file rename or edit)."""
    if content_key is None and not front_matter:
        click.echo("Nothing to update. Pass --content-key <path> and/or --front-matter.", err=True)
        raise click.Abort()

    payload = {"note_id": note_id}
    resolved = None
    if content_key is not None:
        resolved = _compute_content_key(content_key)
        payload["content_key"] = resolved

    if front_matter:
        target_key = resolved
        if target_key is None:
            resp = api_request("GET", "/api/note/detail", params={"note_id": note_id})
            target_key = resp.json()["content_key"]
        filepath = resolve_content_path(target_key)
        if not filepath.is_file():
            click.echo(f"File not found: {filepath}", err=True)
            raise click.Abort()
        parsed = _parse_front_matter(filepath)
        payload["front_matter"] = parsed if parsed is not None else {}

    resp = api_request("POST", "/api/note/update", json=payload)
    note = resp.json()
    parts = [f"content_key = {note['content_key']}"]
    if front_matter:
        parts.append(f"front_matter = {note.get('front_matter')}")
    click.echo(f"Updated note {note['note_id']}: " + ", ".join(parts))
