import click

from .generate import image_generate
from .splice import image_splice
from .tinify import image_tinify


@click.group('image')
def image_group():
    """Image manipulation tools."""
    pass


image_group.add_command(image_generate)
image_group.add_command(image_splice)
image_group.add_command(image_tinify)
