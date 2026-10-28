from datetime import datetime, timezone

import click
from yagent.time_util import utc_to_local
from yagent.api_client import api_request
from yagent.commands.todo.wakeup_text import release_slot_label, wakeup_label


def leader_line(claim: dict) -> str:
    """One compact ownership line. A legacy-marker view keeps a ``(legacy)`` suffix."""
    suffix = " (legacy)" if claim.get("source") == "legacy" else ""
    state = claim.get("state")
    if state == "claimed":
        return f"Leader: claimed by {claim.get('chat_id')} since {claim.get('claimed_at')}{suffix}"
    if state == "released":
        return f"Leader: released{suffix}"
    return f"Leader: free{suffix}"


@click.command('get')
@click.argument('todo_id')
def todo_get(todo_id):
    """Show todo details."""
    resp = api_request("GET", "/api/todo/detail", params={"todo_id": todo_id})
    todo = resp.json()

    click.echo(f"ID:        {todo['todo_id']}")
    click.echo(f"Name:      {todo['name']}")
    click.echo(f"Status:    {todo['status']}")
    wait = todo.get('machine_wait')
    if todo['status'] == 'active' and wait:
        until = utc_to_local(datetime.fromtimestamp(wait['until'] / 1000, tz=timezone.utc).isoformat())
        click.echo(f"Waiting:   {wait['on']} until {until} (chat {wait['chat_id']})")
    click.echo(f"Priority:  {todo.get('priority') or '-'}")
    click.echo(f"Due:       {todo.get('due_date') or '-'}")
    label = wakeup_label(todo)
    if label:
        click.echo(f"Wakeup:    {label}")
    release = release_slot_label(todo)
    if release:
        click.echo(f"Release:   {release}")
    click.echo(f"Tags:      {', '.join(todo['tags']) if todo.get('tags') else '-'}")
    if todo.get('awaiting_chat'):
        click.echo(f"Reply in:  {todo['awaiting_chat']}")
    if todo.get('desc'):
        click.echo(f"Desc:      {todo['desc']}")
    if todo.get('progress'):
        click.echo(f"Progress:  {todo['progress']}")
    if todo.get('leader_claim'):
        click.echo(leader_line(todo['leader_claim']))
    if todo.get('completed_at'):
        click.echo(f"Completed: {todo['completed_at']}")
    if todo.get('created_at'):
        click.echo(f"Created:   {todo['created_at']}")
    if todo.get('notes'):
        click.echo("Notes:")
        for n in todo['notes']:
            tags = ""
            if n.get("front_matter") and n["front_matter"].get("tags"):
                tags = f" [{', '.join(n['front_matter']['tags'])}]"
            click.echo(f"  {n['note_id']}{tags}: {n['content_key']}")
