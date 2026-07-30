import click

from .backfill import backfill
from .credentials_cmd import credentials
from .limits import limits
from .sync import sync


@click.group("usage")
def usage_group():
    """Provider usage: daily token/cost ingestion (sync/backfill) plus
    direct-from-provider subscription limit-window reads (credentials/
    limits), read straight through each vendor CLI's own credential file."""


usage_group.add_command(sync)
usage_group.add_command(backfill)
usage_group.add_command(credentials)
usage_group.add_command(limits)
