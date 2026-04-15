import click

from .import_note import note_import
from .list import note_list
from .get import note_get


@click.group("note")
def note_group():
    """Manage notes."""
    pass


note_group.add_command(note_import)
note_group.add_command(note_list)
note_group.add_command(note_get)
