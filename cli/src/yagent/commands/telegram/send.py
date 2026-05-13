import click
from yagent.api_client import api_request


@click.command('send')
@click.option('-m', '--message', 'text', required=True, help='Message body (markdown ok)')
@click.option('--topic', default=None, help="Forum topic name (omit for DM). 'manager' is an alias for DM.")
def telegram_send(text, topic):
    """Send a Telegram message to the user's DM or a bound forum topic."""
    body = {"text": text}
    if topic is not None:
        body["topic"] = topic
    api_request("POST", "/api/telegram/send", json=body)
    click.echo("sent")
