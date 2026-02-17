import click
from storage.service import todo as todo_service
from storage.service.user import get_cli_user_id


@click.command('deactivate')
@click.argument('todo_id')
def todo_deactivate(todo_id):
    """Set a todo back to pending status."""
    user_id = get_cli_user_id()
    todo = todo_service.deactivate_todo(user_id, todo_id)
    if not todo:
        click.echo(f"Todo '{todo_id}' not found")
        return
    click.echo(f"Deactivated todo '{todo.name}' ({todo.todo_id})")
