import os
import signal
import shutil
import subprocess
import click

from .registry import load_registry, create_worktree, remove_worktree, get_worktree

SESSION_BASE = "/tmp/dev-sessions"


def _run_hook(project_path: str, worktree_path: str, hook_name: str):
    script = os.path.join(project_path, "worktree", f"{hook_name}.sh")
    if not os.path.exists(script):
        return
    click.echo(f"Running {hook_name}.sh ...")
    subprocess.check_call(["bash", script], cwd=worktree_path)
    click.echo(f"{hook_name}.sh done")


def _kill_session_processes(session_dir: str):
    """Kill all tracked processes in a session directory."""
    for pid_file in ["vite.pid", "ngrok.pid", "backend.pid", "ngrok-backend.pid"]:
        path = os.path.join(session_dir, pid_file)
        if not os.path.exists(path):
            continue
        try:
            pid = int(open(path).read().strip())
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, ValueError, OSError):
            pass
    # Remove session dir
    if os.path.exists(session_dir):
        shutil.rmtree(session_dir)


def _cleanup_worktree_artifacts(worktree_path: str):
    """Remove symlinked artifacts from worktree."""
    for rel in ["web/node_modules", "web/.env.local", ".env", ".venv"]:
        p = os.path.join(worktree_path, rel)
        if os.path.exists(p) or os.path.islink(p):
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.remove(p)


def _gc_orphaned_sessions():
    """GC: clean up /tmp/dev-sessions/ entries with no matching active worktree."""
    registry = load_registry()
    active_names = set(registry.keys())
    if not os.path.isdir(SESSION_BASE):
        return
    for entry in os.listdir(SESSION_BASE):
        session_dir = os.path.join(SESSION_BASE, entry)
        if not os.path.isdir(session_dir):
            continue
        if entry not in active_names:
            click.echo(f"  GC: cleaning orphaned session '{entry}'")
            _kill_session_processes(session_dir)


@click.group('wt')
def wt_group():
    """Manage dev worktrees."""
    pass


@click.command('add')
@click.argument('project_path')
@click.argument('name')
@click.option('--todo-id', default=None, help='Associated todo ID')
def wt_add(project_path: str, name: str, todo_id: str):
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

    create_worktree(name, project_path, worktree_path, branch, todo_id=todo_id)
    click.echo(f"Registered worktree '{name}'")


@click.command('rm')
@click.argument('name')
def wt_rm(name: str):
    """Remove a worktree and clean up all associated resources."""
    entry = get_worktree(name)
    project_path = entry["project_path"]
    worktree_path = entry["worktree_path"]
    branch = entry["branch"]

    # 1. Kill processes for this worktree
    session_dir = os.path.join(SESSION_BASE, name)
    _kill_session_processes(session_dir)

    # 2. Clean up worktree artifacts and remove git worktree
    if os.path.exists(worktree_path):
        _cleanup_worktree_artifacts(worktree_path)
        subprocess.check_call(["git", "-C", project_path, "worktree", "remove", "--force", worktree_path])
    if os.path.exists(worktree_path):
        shutil.rmtree(worktree_path)
    subprocess.call(["git", "-C", project_path, "branch", "-D", branch])
    click.echo(f"Removed worktree at {worktree_path}")

    # 3. Reinstall CLI
    cli_dir = os.path.join(project_path, "cli")
    if os.path.isdir(cli_dir):
        subprocess.call(["uv", "tool", "install", "--force", "-e", cli_dir])

    # 4. Unregister
    remove_worktree(name)

    # 5. GC orphaned sessions
    _gc_orphaned_sessions()


@click.command('list')
def wt_list():
    """List all managed worktrees."""
    registry = load_registry()
    if not registry:
        click.echo("No worktrees registered")
        return
    for name, entry in registry.items():
        click.echo(f"  {name} ({entry['project_path']}) -> {entry['worktree_path']}")


@click.command('status')
def wt_status():
    """Show worktrees with server/process status."""
    registry = load_registry()
    if not registry:
        click.echo("No worktrees registered")
        return
    for name, entry in registry.items():
        line = f"  {name} ({entry.get('status', '?')})"
        if entry.get('todo_id'):
            line += f"  todo:{entry['todo_id']}"
        # Check /tmp session for live processes
        session_dir = os.path.join(SESSION_BASE, name)
        services = []
        for svc, pid_file in [("vite", "vite.pid"), ("ngrok", "ngrok.pid"), ("backend", "backend.pid")]:
            pid_path = os.path.join(session_dir, pid_file)
            if os.path.exists(pid_path):
                try:
                    pid = int(open(pid_path).read().strip())
                    os.kill(pid, 0)  # check if alive
                    services.append(svc)
                except (ProcessLookupError, ValueError, OSError):
                    services.append(f"{svc}(dead)")
        if services:
            line += f"  [{', '.join(services)}]"
        click.echo(line)


@click.command('server-sync')
@click.argument('name')
def wt_server_sync(name: str):
    """Sync server state from /tmp/dev-sessions/ to registry."""
    session_dir = os.path.join(SESSION_BASE, name)
    if not os.path.isdir(session_dir):
        click.echo(f"No session directory for '{name}'")
        return

    state = {}
    # Read frontend state
    for key, filename in [("pid", "vite.pid"), ("port", "port"), ("log", "vite.log")]:
        path = os.path.join(session_dir, filename)
        if os.path.exists(path):
            state.setdefault("frontend", {})[key] = open(path).read().strip()
    # Read ngrok frontend state
    for key, filename in [("pid", "ngrok.pid"), ("domain", "ngrok.domain"), ("url", "ngrok.url")]:
        path = os.path.join(session_dir, filename)
        if os.path.exists(path):
            state.setdefault("ngrok_frontend", {})[key] = open(path).read().strip()
    # Read backend state
    for key, filename in [("pid", "backend.pid"), ("port", "backend.port"), ("log", "backend.log")]:
        path = os.path.join(session_dir, filename)
        if os.path.exists(path):
            state.setdefault("backend", {})[key] = open(path).read().strip()
    # Read ngrok backend state
    for key, filename in [("pid", "ngrok-backend.pid"), ("domain", "ngrok-backend.domain"), ("url", "ngrok-backend.url")]:
        path = os.path.join(session_dir, filename)
        if os.path.exists(path):
            state.setdefault("ngrok_backend", {})[key] = open(path).read().strip()

    from .registry import server_sync
    server_sync(name, state)
    click.echo(f"Synced server state for '{name}': {list(state.keys())}")


@click.command('gc')
def wt_gc():
    """Clean up orphaned dev sessions."""
    _gc_orphaned_sessions()
    click.echo("GC complete")


wt_group.add_command(wt_add)
wt_group.add_command(wt_rm)
wt_group.add_command(wt_list)
wt_group.add_command(wt_status)
wt_group.add_command(wt_server_sync)
wt_group.add_command(wt_gc)
