import click

from yagent.commands.init import init
from yagent.commands.chat.click import chat_group
from yagent.commands.bot.click import bot_group
from yagent.commands.todo.click import todo_group
CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

@click.group(context_settings=CONTEXT_SETTINGS)
def cli():
    """Personal command-line toolkit."""
    pass

# Register commands
cli.add_command(init)
cli.add_command(chat_group)
cli.add_command(bot_group)
cli.add_command(todo_group)
