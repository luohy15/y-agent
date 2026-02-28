import click
from yagent.api_client import api_request


@click.command('get')
@click.argument('todo_id')
def todo_get(todo_id):
    """Show todo details."""
    resp = api_request("GET", "/api/todo/detail", params={"todo_id": todo_id})
    todo = resp.json()

    click.echo(f"ID:        {todo['todo_id']}")
    click.echo(f"Name:      {todo['name']}")
    click.echo(f"Status:    {todo['status']}")
    click.echo(f"Priority:  {todo.get('priority') or '-'}")
    click.echo(f"Due:       {todo.get('due_date') or '-'}")
    click.echo(f"Tags:      {', '.join(todo['tags']) if todo.get('tags') else '-'}")
    if todo.get('desc'):
        click.echo(f"Desc:      {todo['desc']}")
    if todo.get('progress'):
        click.echo(f"Progress:  {todo['progress']}")
    if todo.get('completed_at'):
        click.echo(f"Completed: {todo['completed_at']}")
    if todo.get('created_at'):
        click.echo(f"Created:   {todo['created_at']}")
    if todo.get('history'):
        click.echo("History:")
        for h in todo['history']:
            note = f" - {h['note']}" if h.get('note') else ""
            click.echo(f"  {h['timestamp']} {h['action']}{note}")
