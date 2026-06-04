import click

from storage.service import bot_config as bot_service
from storage.service.user import get_cli_user_id


@click.command("disable")
@click.argument("name")
def bot_disable(name):
    """Disable a bot configuration. Disabled bots are excluded from default routing."""
    if name == "default":
        click.echo("Cannot disable the default bot configuration")
        return
    if bot_service.set_enabled(get_cli_user_id(), name, False):
        click.echo(f"Bot '{name}' disabled")
    else:
        click.echo(f"Bot '{name}' not found")