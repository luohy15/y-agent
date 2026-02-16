import click

from .add import calendar_add
from .list import calendar_list
from .get import calendar_get
from .update import calendar_update
from .delete import calendar_delete
from .restore import calendar_restore
from .list_deleted import calendar_list_deleted
from .import_ics import calendar_import
from .export import calendar_export

@click.group('calendar')
def calendar_group():
    """Manage calendar events."""
    pass

calendar_group.add_command(calendar_add)
calendar_group.add_command(calendar_list)
calendar_group.add_command(calendar_get)
calendar_group.add_command(calendar_update)
calendar_group.add_command(calendar_delete)
calendar_group.add_command(calendar_restore)
calendar_group.add_command(calendar_list_deleted)
calendar_group.add_command(calendar_import)
calendar_group.add_command(calendar_export)
