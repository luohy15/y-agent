import click
import httpx
from yagent.api_client import api_request

@click.command('add')
@click.argument('name')
@click.option('--model', '-m', required=True, help='Model name')
@click.option('--api-key', '-k', default='', help='API key')
@click.option('--base-url', '-u', default=None, help='Base URL. For codex backend this is a crs-style prefix (e.g. https://cc1.yovy.app/openai); codex appends the wire path (/responses), so do NOT use a full endpoint or the claude messages-root URL.')
@click.option('--backend', '-b', default=None, help='Backend (e.g. claude_code, codex, gemini_cli, grok_build, perplexity, openai)')
@click.option('--tier', '-t', default=None, help='Tier (tier0|tier1|tier2|tier3, default: tier3)')
@click.option('--type', default=None, help='Type (agent|model, default: agent)')
@click.option('--route-weight', type=float, default=None, help='Route weight for auto-routing (default: 1, 0=paused)')
@click.option('--ref-bot-name', default=None, help='Ref/pointer to another bot (e.g. codex)')
@click.option('--yes', '-y', is_flag=True, help='Overwrite without confirmation')
def bot_add(name, model, api_key, base_url, backend, tier, type, route_weight, ref_bot_name, yes):
    """Add a new bot configuration."""
    try:
        api_request("GET", "/api/bot/config", params={"name": name}).json()
        exists = True
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            raise
        exists = False

    if exists:
        if not yes and not click.confirm(f"Bot '{name}' already exists. Overwrite?"):
            click.echo("Operation cancelled")
            return

    if base_url is None:
        try:
            default_config = api_request("GET", "/api/bot/config", params={"name": "default"}).json()
            base_url = default_config.get("base_url")
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise
            base_url = None

    body = {
        "name": name,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "backend": backend,
        "tier": tier,
        "type": type,
        "route_weight": route_weight,
        "ref_bot_name": ref_bot_name,
    }
    api_request("POST", "/api/bot", json=body)
    click.echo(f"Bot '{name}' added successfully")
