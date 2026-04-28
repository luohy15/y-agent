import click

from .parse import pdf_parse


@click.group('pdf')
def pdf_group():
    """PDF tools."""
    pass


pdf_group.add_command(pdf_parse)
