import click

from .backfill import backfill
from .sync import sync


@click.group("usage")
def usage_group():
    """Provider-generic LLM usage (daily token/cost) ingestion."""


usage_group.add_command(sync)
usage_group.add_command(backfill)
