import click

from .backfill import backfill
from .credentials_cmd import credentials
from .crs_creds import crs_creds
from .limits import limits
from .rate import rate
from .sync import sync


@click.group("usage")
def usage_group():
    """Provider usage: daily token/cost ingestion (sync/backfill) plus
    direct-from-provider subscription limit-window reads (credentials/
    limits), and the direct Relay run-rate path (rate / crs-creds)."""


usage_group.add_command(sync)
usage_group.add_command(backfill)
usage_group.add_command(credentials)
usage_group.add_command(crs_creds)
usage_group.add_command(limits)
usage_group.add_command(rate)
