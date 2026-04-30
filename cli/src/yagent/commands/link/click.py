import click

from .get import link_get
from .import_page import link_import_page
from .list import link_list
from .sync_chrome import link_sync_chrome

@click.group('link')
def link_group():
    """Manage saved links."""
    pass


link_group.add_command(link_get)
link_group.add_command(link_import_page)
link_group.add_command(link_list)
link_group.add_command(link_sync_chrome)
