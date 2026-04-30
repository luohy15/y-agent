import click

from .get import fetch_get


@click.group('fetch')
def fetch_group():
    """Fetch web content and save as markdown."""
    pass


fetch_group.add_command(fetch_get)
