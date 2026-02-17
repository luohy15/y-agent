import click
from storage.service import todo as todo_service
from storage.service.user import get_cli_user_id


@click.command('delete')
@click.argument('todo_id')
def todo_delete(todo_id):
    """Soft delete a todo."""
    user_id = get_cli_user_id()
    todo = todo_service.delete_todo(user_id, todo_id)
    if not todo:
        click.echo(f"Todo '{todo_id}' not found")
        return
    click.echo(f"Deleted todo '{todo.name}' ({todo.todo_id})")
