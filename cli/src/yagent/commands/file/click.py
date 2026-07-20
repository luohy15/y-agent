import click

from .upload import upload
from .download import download


@click.group("file")
def file_group():
    """Transfer files between this Mac and the EC2 host (rsync/SSH)."""
    pass


file_group.add_command(upload)
file_group.add_command(download)
