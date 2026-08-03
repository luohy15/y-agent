import datetime as _dt
import os
import re
from pathlib import Path

import click

from storage.global_config import load_global_config
from yagent.api_client import api_request

DEFAULT_AGENT_HOME = Path("/Users/roy/luohy15")


def agent_home():
    """Return the configured root for local content paths."""
    load_global_config()
    return Path(os.environ.get("Y_AGENT_HOME", DEFAULT_AGENT_HOME)).expanduser().resolve()


def resolve_content_path(filepath):
    """Resolve a local content path relative to the configured agent home."""
    path = Path(filepath).expanduser()
    if not path.is_absolute():
        path = agent_home() / path
    return path.resolve()


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
    """Compute content_key relative to the configured agent home."""
    return os.path.relpath(resolve_content_path(filepath), agent_home())


def import_single(filepath):
    """Import a single file as a note. Returns (content_key, note_id)."""
    resolved_path = resolve_content_path(filepath)
    if not resolved_path.is_file():
        click.echo(f"File not found: {resolved_path}", err=True)
        return None, None
    content_key = _compute_content_key(resolved_path)
    front_matter = _parse_front_matter(resolved_path)
    payload = {"content_key": content_key}
    if front_matter:
        payload["front_matter"] = front_matter
    resp = api_request("POST", "/api/note/import", json=payload)
    note = resp.json()
    return content_key, note["note_id"]


@click.command("import")
@click.argument("paths", nargs=-1, required=True)
def note_import(paths):
    """Import markdown files as notes. Relative paths use $Y_AGENT_HOME."""
    for filepath in paths:
        content_key, note_id = import_single(filepath)
        if note_id:
            click.echo(f"Imported: {content_key} -> {note_id}")
