import click

from .positions import positions


@click.group("finance")
def finance_group():
    """Derived DB-backed finance views."""


finance_group.add_command(positions)
