import click
from storage.service import todo as todo_service
from storage.service.user import get_cli_user_id


@click.command('activate')
@click.argument('todo_id')
def todo_activate(todo_id):
    """Set a todo to active status."""
    user_id = get_cli_user_id()
    todo = todo_service.activate_todo(user_id, todo_id)
    if not todo:
        click.echo(f"Todo '{todo_id}' not found")
        return
    click.echo(f"Activated todo '{todo.name}' ({todo.todo_id})")
