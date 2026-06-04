import click
from storage.service import bot_config as bot_service
from storage.service.user import get_cli_user_id
from agent.pi_models import sync_pi_models

@click.command('delete')
@click.argument('name')
def bot_delete(name):
    """Delete a bot configuration."""
    user_id = get_cli_user_id()
    if bot_service.delete_config(user_id, name):
        sync_pi_models(user_id)
        click.echo(f"Bot '{name}' deleted successfully")
    else:
        if name == "default":
            click.echo("Cannot delete default bot configuration")
        else:
            click.echo(f"Bot '{name}' not found")
