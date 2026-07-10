import click
from storage.service import bot_config as bot_service
from storage.service.user import get_cli_user_id
from agent.pi_models import sync_pi_models

@click.command('rename')
@click.argument('old_name')
@click.argument('new_name')
def bot_rename(old_name, new_name):
    """Rename a bot configuration, cascading ref_bot_name pointers and chat.bot_name."""
    user_id = get_cli_user_id()
    if old_name == "default":
        click.echo("Cannot rename the default bot configuration")
        return
    if bot_service.get_config(user_id, old_name) is None:
        click.echo(f"Bot '{old_name}' not found")
        return
    if bot_service.get_config(user_id, new_name) is not None:
        click.echo(f"Bot '{new_name}' already exists")
        return

    if bot_service.rename_config(user_id, old_name, new_name):
        sync_pi_models(user_id)
        click.echo(f"Bot '{old_name}' renamed to '{new_name}' successfully")
    else:
        click.echo(f"Failed to rename bot '{old_name}'")
