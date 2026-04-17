import click

from .add import reminder_add
from .list import reminder_list
from .cancel import reminder_cancel

@click.group('reminder')
def reminder_group():
    """Manage reminders."""
    pass

reminder_group.add_command(reminder_add)
reminder_group.add_command(reminder_list)
reminder_group.add_command(reminder_cancel)
