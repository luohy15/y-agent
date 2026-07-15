import click
import httpx
from yagent.api_client import api_request

@click.command('rename')
@click.argument('old_name')
@click.argument('new_name')
def bot_rename(old_name, new_name):
    """Rename a bot configuration, cascading ref_bot_name pointers and chat.bot_name."""
    try:
        api_request("POST", "/api/bot/rename", json={"old_name": old_name, "new_name": new_name})
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            click.echo("Cannot rename the default bot configuration")
            return
        if e.response.status_code == 404:
            click.echo(f"Bot '{old_name}' not found")
            return
        if e.response.status_code == 409:
            click.echo(f"Bot '{new_name}' already exists")
            return
        raise

    click.echo(f"Bot '{old_name}' renamed to '{new_name}' successfully")
