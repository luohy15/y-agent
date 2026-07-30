import click

from .usage import usage


@click.group("claude")
def claude_group():
    """Claude Code subscription introspection (e.g. limit-window usage)."""


claude_group.add_command(usage)
