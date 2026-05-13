import click

from .send import telegram_send


@click.group('telegram')
def telegram_group():
    """Send Telegram messages via the y-agent API."""
    pass


telegram_group.add_command(telegram_send)
