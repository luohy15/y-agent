import click

from .splice import image_splice


@click.group('image')
def image_group():
    """Image manipulation tools."""
    pass


image_group.add_command(image_splice)
