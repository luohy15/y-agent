import click
import httpx

from yagent.api_client import api_request


@click.command("enable")
@click.argument("name")
def bot_enable(name):
    """Enable a bot configuration."""
    try:
        api_request("POST", "/api/bot/enable", json={"name": name})
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            click.echo(f"Bot '{name}' not found")
            return
        raise

    click.echo(f"Bot '{name}' enabled")
