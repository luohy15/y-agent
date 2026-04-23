import click

from .unshare import trace_unshare
from .share_list import trace_share_list


@click.group('trace')
def trace_group():
    """Manage trace shares."""
    pass


@trace_group.group('share')
def trace_share_group():
    """Manage trace share links."""
    pass


trace_group.add_command(trace_unshare)
trace_share_group.add_command(trace_share_list)
