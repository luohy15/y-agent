import os
import signal
import shutil
import subprocess
import click

from .registry import load_registry, create_worktree, remove_worktree

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
            # Guard: kill(0,…) signals the whole calling process group; kill(1,…) hits init.
            # A bogus pid file (e.g. "0") would otherwise nuke us.
            if pid > 1:
                os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, ValueError, OSError):
            pass
    if os.path.exists(session_dir):
        try:
            shutil.rmtree(session_dir)
        except OSError as e:
            click.echo(f"  Warning: failed to remove session dir {session_dir}: {e}", err=True)


_HEAVY_DIR_NAMES = (
    "node_modules", "dist", "build", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".next", ".turbo",
)


def _remove_path(p: str):
    """Best-effort remove a file / dir / symlink; warn on failure."""
    if not (os.path.exists(p) or os.path.islink(p)):
        return
    try:
        if os.path.islink(p) or not os.path.isdir(p):
            os.remove(p)
        else:
            shutil.rmtree(p)
    except OSError as e:
        click.echo(f"  Warning: failed to remove {p}: {e}", err=True)


def _cleanup_worktree_artifacts(worktree_path: str):
    """Remove symlinked artifacts and heavy build dirs that can block git worktree remove."""
    for rel in ["web/node_modules", "web/.env.local", ".env", ".venv"]:
        _remove_path(os.path.join(worktree_path, rel))

    for root, dirs, _files in os.walk(worktree_path, topdown=True, followlinks=False):
        dirs[:] = [d for d in dirs if d != ".git"]
        for d in list(dirs):
            if d in _HEAVY_DIR_NAMES or d.endswith(".egg-info"):
                _remove_path(os.path.join(root, d))
                dirs.remove(d)


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
    """Remove a worktree and clean up all associated resources.

    Idempotent: missing or partially-cleaned worktrees emit warnings instead
    of errors so the command always exits 0 unless something catastrophic raises.
    """
    registry = load_registry()
    entry = registry.get(name)

    session_dir = os.path.join(SESSION_BASE, name)
    _kill_session_processes(session_dir)

    if entry is None:
        click.echo(f"Worktree '{name}' not found in registry; skipping git/worktree cleanup.")
        _gc_orphaned_sessions()
        return

    project_path = entry["project_path"]
    worktree_path = entry["worktree_path"]
    branch = entry["branch"]

    if os.path.exists(worktree_path):
        _cleanup_worktree_artifacts(worktree_path)
        rc = subprocess.call(["git", "-C", project_path, "worktree", "remove", "--force", worktree_path])
        if rc != 0:
            click.echo(f"  Warning: git worktree remove failed (rc={rc}); falling back to rmtree", err=True)
    if os.path.exists(worktree_path):
        try:
            shutil.rmtree(worktree_path)
        except OSError as e:
            click.echo(f"  Warning: rmtree failed for {worktree_path}: {e}", err=True)
    subprocess.call(["git", "-C", project_path, "branch", "-D", branch])
    click.echo(f"Removed worktree at {worktree_path}")

    cli_dir = os.path.join(project_path, "cli")
    if os.path.isdir(cli_dir):
        subprocess.call(["uv", "tool", "install", "--force", "-e", cli_dir])

    remove_worktree(name)

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
