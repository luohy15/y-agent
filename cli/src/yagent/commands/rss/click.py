import click

from .add import rss_add
from .import_opml import rss_import_opml
from .list import rss_list
from .list_deleted import rss_list_deleted
from .remove import rss_remove
from .restore import rss_restore


@click.group("rss")
def rss_group():
    """Manage RSS feeds."""
    pass


rss_group.add_command(rss_list)
rss_group.add_command(rss_list_deleted)
rss_group.add_command(rss_add)
rss_group.add_command(rss_remove)
rss_group.add_command(rss_restore)
rss_group.add_command(rss_import_opml)
