import click

from storage.service import bot_config as bot_service
from storage.service.user import get_cli_user_id


@click.command("enable")
@click.argument("name")
def bot_enable(name):
    """Enable a bot configuration."""
    if bot_service.set_enabled(get_cli_user_id(), name, True):
        click.echo(f"Bot '{name}' enabled")
    else:
        click.echo(f"Bot '{name}' not found")