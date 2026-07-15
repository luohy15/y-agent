import click
import httpx

from yagent.api_client import api_request


@click.command("disable")
@click.argument("name")
def bot_disable(name):
    """Disable a bot configuration. Disabled bots are excluded from default routing."""
    try:
        api_request("POST", "/api/bot/disable", json={"name": name})
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            click.echo("Cannot disable the default bot configuration")
            return
        if e.response.status_code == 404:
            click.echo(f"Bot '{name}' not found")
            return
        raise

    click.echo(f"Bot '{name}' disabled")
