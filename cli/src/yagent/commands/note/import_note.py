import datetime as _dt
import os
import re

import click

from yagent.api_client import api_request

BASE_DIR = "/Users/roy/luohy15"


def _json_safe(value):
    """Coerce YAML-parsed values into JSON-serialisable equivalents."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    return value


def _parse_front_matter(filepath):
    """Parse YAML front matter from a markdown file. Returns dict or None."""
    with open(filepath, "r") as f:
        text = f.read()
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return None
    try:
        import yaml
        parsed = yaml.safe_load(match.group(1))
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return _json_safe(parsed)


def _compute_content_key(filepath):
    """Compute content_key as relative path from ~/luohy15/."""
    abs_path = os.path.abspath(filepath)
    return os.path.relpath(abs_path, BASE_DIR)


def import_single(filepath):
    """Import a single file as a note. Returns (content_key, note_id)."""
    if not os.path.isfile(filepath):
        click.echo(f"File not found: {filepath}", err=True)
        return None, None
    content_key = _compute_content_key(filepath)
    front_matter = _parse_front_matter(filepath)
    payload = {"content_key": content_key}
    if front_matter:
        payload["front_matter"] = front_matter
    resp = api_request("POST", "/api/note/import", json=payload)
    note = resp.json()
    return content_key, note["note_id"]


@click.command("import")
@click.argument("paths", nargs=-1, required=True)
def note_import(paths):
    """Import one or more markdown files as notes."""
    for filepath in paths:
        content_key, note_id = import_single(filepath)
        if note_id:
            click.echo(f"Imported: {content_key} -> {note_id}")
