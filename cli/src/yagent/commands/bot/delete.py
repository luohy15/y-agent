import click
import httpx
from yagent.api_client import api_request

@click.command('delete')
@click.argument('name')
def bot_delete(name):
    """Delete a bot configuration."""
    try:
        api_request("POST", "/api/bot/delete", json={"name": name})
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            click.echo("Cannot delete default bot configuration")
            return
        if e.response.status_code == 404:
            click.echo(f"Bot '{name}' not found")
            return
        raise

    click.echo(f"Bot '{name}' deleted successfully")
