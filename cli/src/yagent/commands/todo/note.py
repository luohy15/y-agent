import click
from yagent.api_client import api_request


@click.group('note')
def todo_note():
    """Manage notes on a todo."""
    pass


@todo_note.command('add')
@click.argument('todo_id')
@click.argument('content')
@click.option('-l', '--label', default=None, help='Front-matter label/tag')
def note_add(todo_id, content, label):
    """Create a note and link it to a todo."""
    front_matter = None
    if label:
        front_matter = {"tags": [label]}

    # Create note
    resp = api_request("POST", "/api/note", json={
        "content": content,
        "front_matter": front_matter,
    })
    note = resp.json()
    note_id = note["note_id"]

    # Create relation
    api_request("POST", "/api/note-todo", json={
        "note_id": note_id,
        "todo_id": todo_id,
    })

    click.echo(f"Created note {note_id} and linked to todo {todo_id}")


@todo_note.command('list')
@click.argument('todo_id')
def note_list(todo_id):
    """List notes linked to a todo."""
    resp = api_request("GET", "/api/note-todo/by-todo", params={"todo_id": todo_id})
    note_ids = resp.json()

    if not note_ids:
        click.echo("No notes linked to this todo.")
        return

    for note_id in note_ids:
        resp = api_request("GET", "/api/note/detail", params={"note_id": note_id})
        note = resp.json()
        tags = ""
        if note.get("front_matter") and note["front_matter"].get("tags"):
            tags = f" [{', '.join(note['front_matter']['tags'])}]"
        click.echo(f"  {note['note_id']}{tags}: {note['content']}")


@todo_note.command('remove')
@click.argument('todo_id')
@click.argument('note_id')
def note_remove(todo_id, note_id):
    """Remove a note-todo link (does not delete the note)."""
    api_request("POST", "/api/note-todo/delete", json={
        "note_id": note_id,
        "todo_id": todo_id,
    })
    click.echo(f"Removed link between note {note_id} and todo {todo_id}")
