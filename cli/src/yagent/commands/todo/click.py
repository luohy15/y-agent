import click

from .add import todo_add
from .list import todo_list
from .get import todo_get
from .update import todo_update
from .finish import todo_finish
from .delete import todo_delete
from .activate import todo_activate
from .deactivate import todo_deactivate

@click.group('todo')
def todo_group():
    """Manage todos."""
    pass

todo_group.add_command(todo_add)
todo_group.add_command(todo_list)
todo_group.add_command(todo_get)
todo_group.add_command(todo_update)
todo_group.add_command(todo_finish)
todo_group.add_command(todo_delete)
todo_group.add_command(todo_activate)
todo_group.add_command(todo_deactivate)
