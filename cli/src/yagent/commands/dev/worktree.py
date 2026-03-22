import os
import subprocess
import click

from .registry import load_registry, create_worktree, remove_worktree, get_worktree


def _run_hook(project_path: str, worktree_path: str, hook_name: str):
    script = os.path.join(project_path, "worktree", f"{hook_name}.sh")
    if not os.path.exists(script):
        return
    click.echo(f"Running {hook_name}.sh ...")
    subprocess.check_call(["bash", script], cwd=worktree_path)
    click.echo(f"{hook_name}.sh done")


@click.group('wt')
def wt_group():
    """Manage dev worktrees."""
    pass


@click.command('add')
@click.argument('project_path')
@click.argument('name')
def wt_add(project_path: str, name: str):
    """Create a worktree for a project.

    PROJECT_PATH is the path to the git project root.
    NAME is a short name for this worktree.
    """
    project_path = os.path.abspath(os.path.expanduser(project_path))
    if not os.path.isdir(os.path.join(project_path, ".git")):
        click.echo(f"Error: {project_path} is not a git repository", err=True)
        raise click.Abort()

    # Check if already exists
    registry = load_registry()
    if name in registry:
        click.echo(f"Worktree '{name}' already exists at {registry[name]['worktree_path']}", err=True)
        raise click.Abort()

    repo_name = os.path.basename(project_path)
    worktree_path = os.path.join(os.path.dirname(project_path), f"{repo_name}-{name}")
    branch = f"worktree-{name}"

    if os.path.exists(worktree_path):
        click.echo(f"Error: path already exists: {worktree_path}", err=True)
        raise click.Abort()

    subprocess.check_call(["git", "-C", project_path, "worktree", "add", "-b", branch, worktree_path, "HEAD"])
    click.echo(f"Created worktree at {worktree_path}")

    _run_hook(project_path, worktree_path, "post-create")

    create_worktree(name, project_path, worktree_path, branch)
    click.echo(f"Registered worktree '{name}'")


@click.command('rm')
@click.argument('name')
def wt_rm(name: str):
    """Remove a worktree."""
    entry = get_worktree(name)

    project_path = entry["project_path"]
    worktree_path = entry["worktree_path"]
    branch = entry["branch"]

    if os.path.exists(worktree_path):
        _run_hook(project_path, worktree_path, "pre-remove")
        subprocess.check_call(["git", "-C", project_path, "worktree", "remove", "--force", worktree_path])
    # Safety cleanup: remove any residual files (e.g. from processes that recreate cache dirs)
    if os.path.exists(worktree_path):
        import shutil
        shutil.rmtree(worktree_path)
    subprocess.call(["git", "-C", project_path, "branch", "-D", branch])
    click.echo(f"Removed worktree at {worktree_path}")

    remove_worktree(name)


@click.command('list')
def wt_list():
    """List all managed worktrees."""
    registry = load_registry()
    if not registry:
        click.echo("No worktrees registered")
        return
    for name, entry in registry.items():
        click.echo(f"  {name} ({entry['project_path']}) -> {entry['worktree_path']}")


wt_group.add_command(wt_add)
wt_group.add_command(wt_rm)
wt_group.add_command(wt_list)
