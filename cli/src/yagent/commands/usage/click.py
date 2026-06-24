import click

from .sync import sync


@click.group("usage")
def usage_group():
    """Provider-generic LLM usage (daily token/cost) ingestion."""


usage_group.add_command(sync)
