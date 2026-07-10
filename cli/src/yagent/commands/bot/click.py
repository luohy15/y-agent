import click

from .add import bot_add
from .update import bot_update
from .list import bot_list
from .get import bot_get
from .delete import bot_delete
from .enable import bot_enable
from .disable import bot_disable
from .rename import bot_rename

@click.group('bot')
def bot_group():
    """Manage bot configurations."""
    pass

# Register bot subcommands
bot_group.add_command(bot_add)
bot_group.add_command(bot_update)
bot_group.add_command(bot_list)
bot_group.add_command(bot_get)
bot_group.add_command(bot_delete)
bot_group.add_command(bot_enable)
bot_group.add_command(bot_disable)
bot_group.add_command(bot_rename)
