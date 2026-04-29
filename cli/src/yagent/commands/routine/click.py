import click

from .add import routine_add
from .list import routine_list
from .get import routine_get
from .update import routine_update
from .enable import routine_enable
from .disable import routine_disable
from .delete import routine_delete
from .run import routine_run


@click.group('routine')
def routine_group():
    """Manage scheduled routines (cron-style auto-fired chats)."""
    pass


routine_group.add_command(routine_add)
routine_group.add_command(routine_list)
routine_group.add_command(routine_get)
routine_group.add_command(routine_update)
routine_group.add_command(routine_enable)
routine_group.add_command(routine_disable)
routine_group.add_command(routine_delete)
routine_group.add_command(routine_run)
