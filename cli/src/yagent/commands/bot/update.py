import click
from storage.service import bot_config as bot_service
from storage.service.user import get_cli_user_id
from agent.pi_models import sync_pi_models

@click.command('update')
@click.argument('name')
@click.option('--model', '-m', default=None, help='Model name')
@click.option('--api-key', '-k', default=None, help='API key')
@click.option('--base-url', '-u', default=None, help='Base URL. For codex backend this is a crs-style prefix (e.g. https://cc1.yovy.app/openai); codex appends the wire path (/responses), so do NOT use a full endpoint or the claude messages-root URL.')
@click.option('--backend', '-b', default=None, help='Backend (e.g. claude_code, codex, gemini_cli, perplexity, openai)')
@click.option('--tier', '-t', default=None, help='Tier (tier0|tier1|tier2)')
@click.option('--type', default=None, help='Type (agent|model)')
@click.option('--route-weight', type=float, default=None, help='Route weight for auto-routing (default: 1, 0=paused)')
@click.option('--ref-bot-name', default=None, help='Ref/pointer to another bot (e.g. codex)')
@click.option('--clear-ref-bot-name', is_flag=True, help='Clear the ref bot name')
@click.option('--clear-openrouter', is_flag=True, help='Clear the OpenRouter config')
def bot_update(name, model, api_key, base_url, backend, tier, type, route_weight, ref_bot_name, clear_ref_bot_name, clear_openrouter):
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
    if tier is not None:
        config.tier = tier
    if type is not None:
        config.type = type
    if route_weight is not None:
        config.route_weight = route_weight
    if clear_openrouter:
        config.openrouter_config = None
    if ref_bot_name is not None:
        config.ref_bot_name = ref_bot_name
    if clear_ref_bot_name:
        config.ref_bot_name = None

    bot_service.add_config(user_id, config)
    sync_pi_models(user_id)
    click.echo(f"Bot '{name}' updated successfully")
