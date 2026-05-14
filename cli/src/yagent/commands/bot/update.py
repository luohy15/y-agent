import click
from storage.service import bot_config as bot_service
from storage.service.user import get_cli_user_id

@click.command('update')
@click.argument('name')
@click.option('--model', '-m', default=None, help='Model name')
@click.option('--api-key', '-k', default=None, help='API key')
@click.option('--base-url', '-u', default=None, help='Base URL')
@click.option('--backend', '-b', default=None, help='Backend (e.g. claude_code, codex)')
@click.option('--clear-openrouter', is_flag=True, help='Clear the OpenRouter config')
def bot_update(name, model, api_key, base_url, backend, clear_openrouter):
    """Update an existing bot configuration."""
    user_id = get_cli_user_id()
    config = bot_service.get_config(user_id, name)
    if not config:
        click.echo(f"Bot '{name}' not found")
        return

    if model is not None:
        config.model = model
    if api_key is not None:
        config.api_key = api_key
    if base_url is not None:
        config.base_url = base_url
    if backend is not None:
        config.backend = backend
    if clear_openrouter:
        config.openrouter_config = None

    bot_service.add_config(user_id, config)
    click.echo(f"Bot '{name}' updated successfully")
