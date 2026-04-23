import os

import click

from yagent.api_client import api_request
from yagent.commands.note.import_note import import_single as import_note_single, _parse_front_matter


def _derive_name(front_matter, filepath):
    if front_matter and isinstance(front_matter, dict) and front_matter.get("name"):
        return str(front_matter["name"])
    return os.path.basename(filepath).removesuffix(".md")


def _derive_type(front_matter):
    if front_matter and isinstance(front_matter, dict) and front_matter.get("type"):
        return str(front_matter["type"])
    return None


def import_single(filepath):
    """Import a markdown file as a note + entity, and link them.
    Returns (entity_id, note_id)."""
    if not os.path.isfile(filepath):
        click.echo(f"File not found: {filepath}", err=True)
        return None, None

    content_key, note_id = import_note_single(filepath)
    if not note_id:
        return None, None

    front_matter = _parse_front_matter(filepath)
    name = _derive_name(front_matter, filepath)
    type_ = _derive_type(front_matter)
    if not type_:
        type_ = "person"
        click.echo(f"  warn: no 'type' in front matter, defaulting to 'person'", err=True)

    payload = {"name": name, "type": type_}
    if front_matter:
        payload["front_matter"] = front_matter
    resp = api_request("POST", "/api/entity/import", json=payload)
    entity = resp.json()
    entity_id = entity["entity_id"]

    api_request("POST", "/api/entity-note", json={"entity_id": entity_id, "note_id": note_id})
    return entity_id, note_id


@click.command("import")
@click.argument("paths", nargs=-1, required=True)
def entity_import(paths):
    """Import one or more markdown files as entities (creates note + entity + link)."""
    for filepath in paths:
        entity_id, note_id = import_single(filepath)
        if entity_id:
            click.echo(f"Imported: {filepath} -> entity {entity_id} (note {note_id})")
