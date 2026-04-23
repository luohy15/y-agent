import click

from .import_entity import entity_import
from .list import entity_list
from .get import entity_get


@click.group("entity")
def entity_group():
    """Manage entities (knowledge-graph nodes)."""
    pass


entity_group.add_command(entity_import)
entity_group.add_command(entity_list)
entity_group.add_command(entity_get)
