import click
from storage.service import todo as todo_service
from storage.service.user import get_cli_user_id


@click.command('update')
@click.argument('todo_id')
@click.option('--name', '-n', default=None, help='New name')
@click.option('--desc', '-d', default=None, help='New description')
@click.option('--due', '-u', default=None, help='New due date (YYYY-MM-DD)')
@click.option('--priority', '-p', default=None, type=click.Choice(['low', 'medium', 'high', 'none']), help='New priority')
@click.option('--tags', '-t', default=None, help='New comma-separated tags')
@click.option('--progress', default=None, help='Progress note')
def todo_update(todo_id, name, desc, due, priority, tags, progress):
    """Update a todo."""
    user_id = get_cli_user_id()
    fields = {}
    if name is not None:
        fields['name'] = name
    if desc is not None:
        fields['desc'] = desc
    if due is not None:
        fields['due_date'] = due
    if priority is not None:
        fields['priority'] = priority
    if tags is not None:
        fields['tags'] = [t.strip() for t in tags.split(',')]
    if progress is not None:
        fields['progress'] = progress

    if not fields:
        click.echo("No fields to update")
        return

    todo = todo_service.update_todo(user_id, todo_id, **fields)
    if not todo:
        click.echo(f"Todo '{todo_id}' not found")
        return
    click.echo(f"Updated todo '{todo.name}' ({todo.todo_id})")
