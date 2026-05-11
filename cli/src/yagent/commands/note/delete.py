import click
import httpx

from yagent.api_client import api_request


@click.command("delete")
@click.argument("note_id")
@click.option("--force", "-f", is_flag=True, default=False, help="Unlink note_todo relations before deleting")
def note_delete(note_id, force):
    """Soft-delete a note (sets deleted_at).

    Refuses if the note has live note_todo relations unless --force is set;
    always refuses if an entity backs the note (delete the entity first).
    """
    try:
        resp = api_request("POST", "/api/note/delete", json={"note_id": note_id, "force": force})
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            try:
                body = e.response.json().get("detail", {})
            except Exception:
                body = {}
            reason = body.get("reason", "refused")
            todo_n = body.get("todo_relations", 0)
            entity_n = body.get("entity_relations", 0)
            click.echo(f"Refused: {reason}", err=True)
            click.echo(f"  todo_relations: {todo_n}", err=True)
            click.echo(f"  entity_relations: {entity_n}", err=True)
            if entity_n > 0:
                click.echo("Hint: remove the backing entity first (y entity ...).", err=True)
            elif todo_n > 0 and not force:
                click.echo("Hint: rerun with --force to unlink note_todo relations and delete.", err=True)
            raise click.Abort()
        raise

    body = resp.json()
    if body.get("deleted"):
        click.echo(f"Deleted note {note_id}")
    else:
        click.echo(f"Note {note_id} not found (nothing to delete)")
