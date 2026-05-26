import click

from yagent.commands.cookies.delete import cookies_delete
from yagent.commands.cookies.list import cookies_list
from yagent.commands.cookies.sync import cookies_sync


@click.group(name="cookies")
def cookies_group():
    """Manage browser cookies synced to the y-agent API."""


cookies_group.add_command(cookies_sync)
cookies_group.add_command(cookies_list)
cookies_group.add_command(cookies_delete)
