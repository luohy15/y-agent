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
def todo_update(todo_id, name, desc, due, priority, tags, progress):
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

    if len(body) == 1:
        click.echo("No fields to update")
        return

    resp = api_request("POST", "/api/todo/update", json=body)
    todo = resp.json()
    click.echo(f"Updated todo '{todo['name']}' ({todo['todo_id']})")
