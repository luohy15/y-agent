import click

from .get import email_get
from .list import email_list
from .sync_gmail import email_sync_gmail


@click.group('email')
def email_group():
    """Manage emails."""
    pass


email_group.add_command(email_get)
email_group.add_command(email_list)
email_group.add_command(email_sync_gmail)
