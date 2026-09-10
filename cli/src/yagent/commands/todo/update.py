import click
from yagent.api_client import api_request
from yagent.tag_option import resolve_tags


@click.command('update')
@click.argument('todo_id')
@click.option('--name', '-n', default=None, help='New name')
@click.option('--desc', '-d', default=None, help='New description')
@click.option('--due', '-u', default=None, help='New due date (YYYY-MM-DD)')
@click.option('--priority', '-p', default=None, type=click.Choice(['low', 'medium', 'high', 'none']), help='New priority')
@click.option('--tags', '-t', 'tags', multiple=True,
              help='New tags: repeat -t and/or comma-separate; replaces the whole set '
                   '(e.g. -t cli -t "agent-config,tags"); -t "" clears all tags')
@click.option('--progress', default=None, help='Progress note')
@click.option('--awaiting', type=click.Choice(['question', 'review', 'external', 'none']),
              help='Declare a wait, or none to clear it; stalled is host-internal')
@click.option('--awaiting-chat', help='Same-trace public chat ID required for question')
@click.option('--awaiting-until', help='Timezone-aware ISO deadline for external (default grace: 60 minutes)')
def todo_update(todo_id, name, desc, due, priority, tags, progress, awaiting, awaiting_chat, awaiting_until):
    """Update a todo."""
    body = {"todo_id": todo_id}
    if name is not None:
        body["name"] = name
    if desc is not None:
        body["desc"] = desc
    if due is not None:
        body["due_date"] = due
    if priority is not None:
        body["priority"] = priority
    resolved_tags = resolve_tags(tags)
    if resolved_tags is not None:
        body["tags"] = resolved_tags
    if progress is not None:
        body["progress"] = progress

    if awaiting is not None:
        body["awaiting"] = None if awaiting == "none" else awaiting
    if awaiting_chat is not None:
        body["awaiting_chat"] = awaiting_chat
    if awaiting_until is not None:
        body["awaiting_until"] = awaiting_until

    if len(body) == 1:
        click.echo("No fields to update")
        return

    resp = api_request("POST", "/api/todo/update", json=body)
    todo = resp.json()
    click.echo(f"Updated todo '{todo['name']}' ({todo['todo_id']})")
