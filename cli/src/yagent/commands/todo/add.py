import click
from yagent.api_client import api_request
from yagent.tag_option import resolve_tags


@click.command('add')
@click.argument('name')
@click.option('--desc', '-d', default=None, help='Description')
@click.option('--due', '-u', default=None, help='Due date (YYYY-MM-DD)')
@click.option('--priority', '-p', default=None, type=click.Choice(['low', 'medium', 'high', 'none']), help='Priority')
@click.option('--tags', '-t', 'tags', multiple=True,
              help='Tags: repeat -t and/or comma-separate (e.g. -t cli -t "agent-config,tags")')
def todo_add(name, desc, due, priority, tags):
    """Add a new todo."""
    body = {"name": name}
    if desc is not None:
        body["desc"] = desc
    if due is not None:
        body["due_date"] = due
    if priority is not None:
        body["priority"] = priority
    resolved_tags = resolve_tags(tags)
    if resolved_tags is not None:
        body["tags"] = resolved_tags

    resp = api_request("POST", "/api/todo", json=body)
    todo = resp.json()
    click.echo(f"Created todo '{todo['name']}' ({todo['todo_id']})")
