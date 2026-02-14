import click
from storage.entity.dto import BotConfig
from storage.service import bot_config as bot_service
from storage.service.user import get_cli_user_id

@click.command('add')
@click.argument('name')
@click.option('--model', '-m', required=True, help='Model name')
@click.option('--api-key', '-k', default='', help='API key')
@click.option('--base-url', '-u', default=None, help='Base URL')
@click.option('--api-type', '-t', default=None, help='API type (e.g. anthropic)')
@click.option('--yes', '-y', is_flag=True, help='Overwrite without confirmation')
def bot_add(name, model, api_key, base_url, api_type, yes):
    """Add a new bot configuration."""
    user_id = get_cli_user_id()
    existing_configs = bot_service.list_configs(user_id)
    if any(config.name == name for config in existing_configs):
        if not yes and not click.confirm(f"Bot '{name}' already exists. Overwrite?"):
            click.echo("Operation cancelled")
            return

    default_config = bot_service.default_config
    if base_url is None:
        base_url = default_config.base_url

    bot_config = BotConfig(name=name, api_key=api_key, base_url=base_url, model=model, api_type=api_type)
    bot_service.add_config(user_id, bot_config)
    click.echo(f"Bot '{name}' added successfully")
