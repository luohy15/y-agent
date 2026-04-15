import os

import click

from yagent.api_client import api_request
from yagent.commands.note.import_note import import_single as import_note_single


def _resolve_activity_id(id_value):
    """If id_value looks like a file path, import it as a page link and return the activity_id.
    Otherwise return id_value as-is."""
    if '/' in id_value or id_value.endswith('.md'):
        if not os.path.isfile(id_value):
            click.echo(f"File not found: {id_value}", err=True)
            raise SystemExit(1)
        title = os.path.basename(id_value).removesuffix('.md')
        with open(id_value, 'r') as f:
            content = f.read()
        resp = api_request("POST", "/api/link/from-page", json={"path": id_value, "title": title, "content": content})
        data = resp.json()
        activity_id = data.get('activity_id')
        click.echo(f"Imported: {id_value} -> {data.get('link_id', '?')}")
        return activity_id
    return id_value


def _resolve_note_id(id_value):
    """If id_value looks like a file path, import it as a note and return the note_id.
    Otherwise return id_value as-is."""
    if '/' in id_value or id_value.endswith('.md'):
        _content_key, note_id = import_note_single(id_value)
        if not note_id:
            raise SystemExit(1)
        return note_id
    return id_value


@click.group("assoc")
def assoc_group():
    """Associate resources with a todo."""
    pass


@assoc_group.command("note")
@click.argument("ids", nargs=-1, required=True)
@click.option("--todo", "-t", required=True, help="Todo ID to associate with")
def assoc_note(ids, todo):
    """Associate notes with a todo. Each ID can be a note_id or a local file path."""
    for id_value in ids:
        try:
            note_id = _resolve_note_id(id_value)
            api_request("POST", "/api/note-todo", json={"note_id": note_id, "todo_id": todo})
            click.echo(f"Linked note {note_id} to todo {todo}")
        except (SystemExit, Exception) as e:
            click.echo(f"  ! {id_value}: {e}", err=True)


@assoc_group.command("link")
@click.argument("ids", nargs=-1, required=True)
@click.option("--todo", "-t", required=True, help="Todo ID to associate with")
def assoc_link(ids, todo):
    """Associate links with a todo. Each ID can be an activity_id or a local file path."""
    activity_ids = []
    for id_value in ids:
        try:
            activity_ids.append(_resolve_activity_id(id_value))
        except (SystemExit, Exception) as e:
            click.echo(f"  ! {id_value}: {e}", err=True)

    if not activity_ids:
        return

    resp = api_request("POST", "/api/link-todo/batch", json={"activity_ids": activity_ids, "todo_id": todo})
    data = resp.json()
    click.echo(f"Associated {data.get('created', 0)}/{len(activity_ids)} links with todo {todo}")


@click.group("unassoc")
def unassoc_group():
    """Remove resource associations from a todo."""
    pass


@unassoc_group.command("note")
@click.argument("note_id")
@click.option("--todo", "-t", required=True, help="Todo ID to disassociate from")
def unassoc_note(note_id, todo):
    """Remove association between a note and a todo."""
    api_request("POST", "/api/note-todo/delete", json={"note_id": note_id, "todo_id": todo})
    click.echo(f"Removed link between note {note_id} and todo {todo}")


@unassoc_group.command("link")
@click.argument("activity_id")
@click.option("--todo", "-t", required=True, help="Todo ID to disassociate from")
def unassoc_link(activity_id, todo):
    """Remove association between a link activity and a todo."""
    resp = api_request("POST", "/api/link-todo/delete", json={"activity_id": activity_id, "todo_id": todo})
    data = resp.json()
    if data.get("deleted"):
        click.echo(f"Removed association between activity {activity_id} and todo {todo}")
    else:
        click.echo(f"Association not found")
