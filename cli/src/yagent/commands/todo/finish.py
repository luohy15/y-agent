import click
from storage.service import todo as todo_service
from storage.service.user import get_cli_user_id
from .dashboard import update_dashboard


@click.command('finish')
@click.argument('todo_id')
def todo_finish(todo_id):
    """Mark a todo as completed."""
    user_id = get_cli_user_id()
    todo = todo_service.finish_todo(user_id, todo_id)
    if not todo:
        click.echo(f"Todo '{todo_id}' not found")
        return
    click.echo(f"Completed todo '{todo.name}' ({todo.todo_id})")
    update_dashboard(user_id)
