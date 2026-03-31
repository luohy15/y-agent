import click

from .download import link_download
from .list import link_list
from .sync_chrome import link_sync_chrome
from .assoc import link_assoc, link_unassoc


@click.group('link')
def link_group():
    """Manage saved links."""
    pass


link_group.add_command(link_download)
link_group.add_command(link_list)
link_group.add_command(link_sync_chrome)
link_group.add_command(link_assoc)
link_group.add_command(link_unassoc)
