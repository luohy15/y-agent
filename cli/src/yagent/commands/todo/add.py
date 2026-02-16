import click
from storage.service import todo as todo_service
from storage.service.user import get_cli_user_id
from .dashboard import update_dashboard


@click.command('add')
@click.argument('name')
@click.option('--desc', '-d', default=None, help='Description')
@click.option('--due', '-u', default=None, help='Due date (YYYY-MM-DD)')
@click.option('--priority', '-p', default=None, type=click.Choice(['low', 'medium', 'high', 'none']), help='Priority')
@click.option('--tags', '-t', default=None, help='Comma-separated tags')
def todo_add(name, desc, due, priority, tags):
    """Add a new todo."""
    user_id = get_cli_user_id()
    tag_list = [t.strip() for t in tags.split(',')] if tags else None
    todo = todo_service.create_todo(user_id, name, desc=desc, tags=tag_list, due_date=due, priority=priority)
    click.echo(f"Created todo '{todo.name}' ({todo.todo_id})")
    update_dashboard(user_id)
