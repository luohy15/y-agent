import click

from .get import link_get
from .fetch import link_fetch
from .import_page import link_import_page
from .list import link_list
from .sync_chrome import link_sync_chrome
from .tldr import link_tldr

@click.group('link')
def link_group():
    """Manage saved links."""
    pass


link_group.add_command(link_get)
link_group.add_command(link_fetch)
link_group.add_command(link_import_page)
link_group.add_command(link_list)
link_group.add_command(link_sync_chrome)
link_group.add_command(link_tldr)
