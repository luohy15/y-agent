import click

from .add import rss_add
from .import_opml import rss_import_opml
from .list import rss_list
from .remove import rss_remove


@click.group("rss")
def rss_group():
    """Manage RSS feeds."""
    pass


rss_group.add_command(rss_list)
rss_group.add_command(rss_add)
rss_group.add_command(rss_remove)
rss_group.add_command(rss_import_opml)
