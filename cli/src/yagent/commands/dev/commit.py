import subprocess
import click

from .registry import get_worktree


@click.command('commit')
@click.argument('worktree_name')
@click.option('--message', '-m', default=None, help='Commit message (default: worktree name)')
def dev_commit(worktree_name: str, message: str):
    """Commit worktree changes, rebase onto main, and fast-forward main."""
    entry = get_worktree(worktree_name)
    work_dir = entry["worktree_path"]
    project_path = entry["project_path"]
    branch = entry["branch"]

    git = ["git", "-C", work_dir]
    commit_msg = message or worktree_name

    # Check for changes
    status = subprocess.run(git + ["status", "--porcelain"], capture_output=True, text=True)
    if not status.stdout.strip():
        click.echo("No changes to commit")
    else:
        subprocess.check_call(git + ["add", "-A"])
        subprocess.check_call(git + ["commit", "-m", commit_msg])
        click.echo("Committed changes")

    # Rebase onto main
    subprocess.check_call(git + ["rebase", "main"])
    click.echo("Rebased onto main")

    # Fast-forward main from the main repo
    subprocess.check_call(["git", "-C", project_path, "merge", "--ff-only", branch])
    click.echo(f"Fast-forwarded main to {branch}")
