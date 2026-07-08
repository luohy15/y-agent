import click
from storage.entity.dto import BotConfig
from storage.service import bot_config as bot_service
from storage.service.user import get_cli_user_id
from agent.pi_models import sync_pi_models

@click.command('add')
@click.argument('name')
@click.option('--model', '-m', required=True, help='Model name')
@click.option('--api-key', '-k', default='', help='API key')
@click.option('--base-url', '-u', default=None, help='Base URL. For codex backend this is a crs-style prefix (e.g. https://cc1.yovy.app/openai); codex appends the wire path (/responses), so do NOT use a full endpoint or the claude messages-root URL.')
@click.option('--backend', '-b', default=None, help='Backend (e.g. claude_code, codex, gemini_cli, perplexity, openai)')
@click.option('--tier', '-t', default=None, help='Tier (tier0|tier1|tier2|tier3, default: tier3)')
@click.option('--type', default=None, help='Type (agent|model, default: agent)')
@click.option('--route-weight', type=float, default=None, help='Route weight for auto-routing (default: 1, 0=paused)')
@click.option('--ref-bot-name', default=None, help='Ref/pointer to another bot (e.g. codex)')
@click.option('--yes', '-y', is_flag=True, help='Overwrite without confirmation')
def bot_add(name, model, api_key, base_url, backend, tier, type, route_weight, ref_bot_name, yes):
    """Add a new bot configuration."""
    user_id = get_cli_user_id()
    existing_configs = bot_service.list_configs(user_id)
    if any(config.name == name for config in existing_configs):
        if not yes and not click.confirm(f"Bot '{name}' already exists. Overwrite?"):
            click.echo("Operation cancelled")
            return

    default_config = bot_service.get_config(user_id)
    if base_url is None:
        base_url = default_config.base_url if default_config else None

    bot_config = BotConfig(name=name, api_key=api_key, base_url=base_url, model=model, backend=backend, tier=tier, type=type, route_weight=route_weight, ref_bot_name=ref_bot_name)
    bot_service.add_config(user_id, bot_config)
    sync_pi_models(user_id)
    click.echo(f"Bot '{name}' added successfully")
