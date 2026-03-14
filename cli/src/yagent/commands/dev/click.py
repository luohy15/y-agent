import click

from .worktree import wt_group
from .run import dev_run
from .commit import dev_commit


@click.group('dev')
def dev_group():
    """Dev workflow: manage worktrees, submit work, commit."""
    pass


dev_group.add_command(wt_group)
dev_group.add_command(dev_run)
dev_group.add_command(dev_commit)
