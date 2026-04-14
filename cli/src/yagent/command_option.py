import click
from storage.global_config import load_global_config

from yagent.commands.init import init
from yagent.commands.login import login
from yagent.commands.logout import logout
from yagent.commands.chat.click import chat_group
from yagent.commands.bot.click import bot_group
from yagent.commands.todo.click import todo_group
from yagent.commands.calendar.click import calendar_group
from yagent.commands.link.click import link_group
from yagent.commands.email.click import email_group
from yagent.commands.beancount.click import beancount_group
from yagent.commands.image.click import image_group
from yagent.commands.dev.click import dev_group
from yagent.commands.notify import notify
CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

@click.group(context_settings=CONTEXT_SETTINGS)
def cli():
    """Personal command-line toolkit."""
    load_global_config()


# Register commands
cli.add_command(init)
cli.add_command(login)
cli.add_command(logout)
cli.add_command(chat_group)
cli.add_command(bot_group)
cli.add_command(todo_group)
cli.add_command(calendar_group)
cli.add_command(link_group)
cli.add_command(email_group)
cli.add_command(beancount_group)
cli.add_command(image_group)
cli.add_command(dev_group)
cli.add_command(notify)
