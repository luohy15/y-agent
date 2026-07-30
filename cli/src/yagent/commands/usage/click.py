import click

from .backfill import backfill
from .limits import limits
from .login import credentials, login
from .sync import sync


@click.group("usage")
def usage_group():
    """Provider usage: daily token/cost ingestion (sync/backfill) plus
    direct-from-provider subscription limit-window credentials (login/
    credentials/limits)."""


usage_group.add_command(sync)
usage_group.add_command(backfill)
usage_group.add_command(login)
usage_group.add_command(credentials)
usage_group.add_command(limits)
