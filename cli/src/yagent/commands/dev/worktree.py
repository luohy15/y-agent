import os
import subprocess
import click

from .registry import load_registry, save_registry


def _apply_symlinks(git_root: str, worktree_path: str):
    symlinks_file = os.path.join(git_root, ".symlinks")
    if not os.path.exists(symlinks_file):
        return
    with open(symlinks_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            src, dst = line.split(",", 1)
            src = src.strip()
            dst = dst.strip()
            if not os.path.isabs(src):
                src = os.path.join(worktree_path, src)
            else:
                src = os.path.expanduser(src)
            target = os.path.join(worktree_path, dst)
            if not os.path.exists(target):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.symlink(src, target)


def _run_post_create(project_path: str, worktree_path: str):
    script = os.path.join(project_path, "worktree", "post-create.sh")
    if not os.path.exists(script):
        return
    click.echo(f"Running post-create.sh ...")
    subprocess.check_call(["bash", script], cwd=worktree_path)
    click.echo("post-create.sh done")


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

    _apply_symlinks(project_path, worktree_path)
    _run_post_create(project_path, worktree_path)

    registry[name] = {
        "project_path": project_path,
        "worktree_path": worktree_path,
        "branch": branch,
    }
    save_registry(registry)
    click.echo(f"Registered worktree '{name}'")


@click.command('rm')
@click.argument('name')
def wt_rm(name: str):
    """Remove a worktree."""
    registry = load_registry()
    if name not in registry:
        click.echo(f"Worktree '{name}' not found", err=True)
        raise click.Abort()

    entry = registry[name]
    project_path = entry["project_path"]
    worktree_path = entry["worktree_path"]
    branch = entry["branch"]

    if os.path.exists(worktree_path):
        subprocess.check_call(["git", "-C", project_path, "worktree", "remove", "--force", worktree_path])
    subprocess.call(["git", "-C", project_path, "branch", "-D", branch])
    click.echo(f"Removed worktree at {worktree_path}")

    del registry[name]
    save_registry(registry)


@click.command('list')
def wt_list():
    """List all managed worktrees."""
    registry = load_registry()
    if not registry:
        click.echo("No worktrees registered")
        return
    for name, entry in registry.items():
        click.echo(f"  {name}: {entry['worktree_path']}  (project: {entry['project_path']})")


wt_group.add_command(wt_add)
wt_group.add_command(wt_rm)
wt_group.add_command(wt_list)
