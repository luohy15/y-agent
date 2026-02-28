import click
from yagent.api_client import api_request


@click.command('add')
@click.argument('name')
@click.option('--desc', '-d', default=None, help='Description')
@click.option('--due', '-u', default=None, help='Due date (YYYY-MM-DD)')
@click.option('--priority', '-p', default=None, type=click.Choice(['low', 'medium', 'high', 'none']), help='Priority')
@click.option('--tags', '-t', default=None, help='Comma-separated tags')
def todo_add(name, desc, due, priority, tags):
    """Add a new todo."""
    body = {"name": name}
    if desc is not None:
        body["desc"] = desc
    if due is not None:
        body["due_date"] = due
    if priority is not None:
        body["priority"] = priority
    if tags is not None:
        body["tags"] = [t.strip() for t in tags.split(',')]

    resp = api_request("POST", "/api/todo", json=body)
    todo = resp.json()
    click.echo(f"Created todo '{todo['name']}' ({todo['todo_id']})")
