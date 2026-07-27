import click

from .add import english_add
from .list import english_list
from .get import english_get
from .dismiss import english_dismiss
from .pending import english_pending
from .mark_scanned import english_mark_scanned


@click.group("english")
def english_group():
    """Manage English grammar corrections (offline hourly scan)."""
    pass


english_group.add_command(english_add)
english_group.add_command(english_list)
english_group.add_command(english_get)
english_group.add_command(english_dismiss)
english_group.add_command(english_pending)
english_group.add_command(english_mark_scanned)
