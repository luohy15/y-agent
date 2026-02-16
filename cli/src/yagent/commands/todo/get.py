import click
from storage.service import todo as todo_service
from storage.service.user import get_cli_user_id


@click.command('get')
@click.argument('todo_id')
def todo_get(todo_id):
    """Show todo details."""
    user_id = get_cli_user_id()
    todo = todo_service.get_todo(user_id, todo_id)
    if not todo:
        click.echo(f"Todo '{todo_id}' not found")
        return

    click.echo(f"ID:        {todo.todo_id}")
    click.echo(f"Name:      {todo.name}")
    click.echo(f"Status:    {todo.status}")
    click.echo(f"Priority:  {todo.priority or '-'}")
    click.echo(f"Due:       {todo.due_date or '-'}")
    click.echo(f"Tags:      {', '.join(todo.tags) if todo.tags else '-'}")
    if todo.desc:
        click.echo(f"Desc:      {todo.desc}")
    if todo.progress:
        click.echo(f"Progress:  {todo.progress}")
    if todo.completed_at:
        click.echo(f"Completed: {todo.completed_at}")
    if todo.created_at:
        click.echo(f"Created:   {todo.created_at}")
    if todo.history:
        click.echo("History:")
        for h in todo.history:
            note = f" - {h.note}" if h.note else ""
            click.echo(f"  {h.timestamp} {h.action}{note}")
