import click
import httpx
from yagent.api_client import api_request

@click.command('update')
@click.argument('name')
@click.option('--model', '-m', default=None, help='Model name')
@click.option('--api-key', '-k', default=None, help='API key')
@click.option('--base-url', '-u', default=None, help='Base URL. For codex backend this is a crs-style prefix (e.g. https://cc1.yovy.app/openai); codex appends the wire path (/responses), so do NOT use a full endpoint or the claude messages-root URL.')
@click.option('--backend', '-b', default=None, help='Backend (e.g. claude_code, codex, gemini_cli, grok_build, perplexity, openai)')
@click.option('--tier', '-t', default=None, help='Tier (tier0|tier1|tier2|tier3, default: tier3)')
@click.option('--clear-tier', is_flag=True, help='Clear the tier (set to NULL, falls back to system default)')
@click.option('--type', default=None, help='Type (agent|model)')
@click.option('--route-weight', type=float, default=None, help='Route weight for auto-routing (default: 1, 0=paused)')
@click.option('--ref-bot-name', default=None, help='Ref/pointer to another bot (e.g. codex)')
@click.option('--clear-ref-bot-name', is_flag=True, help='Clear the ref bot name')
@click.option('--clear-openrouter', is_flag=True, help='Clear the OpenRouter config')
def bot_update(name, model, api_key, base_url, backend, tier, clear_tier, type, route_weight, ref_bot_name, clear_ref_bot_name, clear_openrouter):
    """Update an existing bot configuration."""
    body = {"name": name}
    if model is not None:
        body["model"] = model
    if api_key is not None:
        body["api_key"] = api_key
    if base_url is not None:
        body["base_url"] = base_url
    if backend is not None:
        body["backend"] = backend
    if tier is not None:
        body["tier"] = tier
    if clear_tier:
        body["tier"] = ""
    if type is not None:
        body["type"] = type
    if route_weight is not None:
        body["route_weight"] = route_weight
    if clear_openrouter:
        body["clear_openrouter"] = True
    if ref_bot_name is not None:
        body["ref_bot_name"] = ref_bot_name
    if clear_ref_bot_name:
        body["ref_bot_name"] = ""

    try:
        api_request("POST", "/api/bot/update", json=body)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            click.echo(f"Bot '{name}' not found")
            return
        raise

    click.echo(f"Bot '{name}' updated successfully")
