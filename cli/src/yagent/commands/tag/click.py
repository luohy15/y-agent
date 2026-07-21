import click

from .get import tag_get
from .list import tag_list
from .add import tag_add
from .rm import tag_rm


@click.group("tag")
def tag_group():
    """Cross-entity tag lookup (entity_tag)."""
    pass


tag_group.add_command(tag_get)
tag_group.add_command(tag_list)
tag_group.add_command(tag_add)
tag_group.add_command(tag_rm)
