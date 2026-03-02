import click

from .list import link_list
from .sync_chrome import link_sync_chrome


@click.group('link')
def link_group():
    """Manage saved links."""
    pass


link_group.add_command(link_list)
link_group.add_command(link_sync_chrome)
