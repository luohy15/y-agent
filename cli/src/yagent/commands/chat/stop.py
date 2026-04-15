import click

from yagent.api_client import api_request


@click.command('stop')
@click.argument('chat_id')
def stop_chat(chat_id: str):
    """Stop a running chat by ID."""
    try:
        api_request("POST", "/api/chat/stop", json={"chat_id": chat_id})
        click.echo(f"Stopped chat {chat_id}")
    except Exception as e:
        click.echo(f"Error: {e}")
        raise click.Abort()
