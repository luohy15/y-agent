import click

from yagent.commands.access.approve import access_approve
from yagent.commands.access.inventory import access_inventory
from yagent.commands.access.list import access_list


@click.group(name="access")
def access_group():
    """List, approve, and inventory homepage admission."""


access_group.add_command(access_list)
access_group.add_command(access_approve)
access_group.add_command(access_inventory)
