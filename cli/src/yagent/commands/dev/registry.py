"""Worktree registry: API-first with local JSON fallback (~/.y-agent/dev-worktrees.json)."""
import json
import os

from yagent.api_client import api_request


# ---------------------------------------------------------------------------
# Local JSON fallback
# ---------------------------------------------------------------------------

def _registry_path() -> str:
    home = os.path.expanduser(os.getenv("Y_AGENT_HOME", "~/.y-agent"))
    return os.path.join(home, "dev-worktrees.json")


def _load_local_registry() -> dict[str, dict]:
    path = _registry_path()
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _save_local_registry(registry: dict[str, dict]):
    path = _registry_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(registry, f, indent=2)


# ---------------------------------------------------------------------------
# Public API (API-first, JSON fallback)
# ---------------------------------------------------------------------------

def load_registry() -> dict[str, dict]:
    """Load all worktrees as {name: {...}}."""
    try:
        resp = api_request("GET", "/api/dev-worktree/list", params={"status": "active"})
        worktrees = resp.json()
        return {w["name"]: w for w in worktrees}
    except Exception:
        return _load_local_registry()


def save_registry(registry: dict[str, dict]):
    """Save registry (local-only fallback, API handles persistence via individual calls)."""
    _save_local_registry(registry)


def get_worktree(name: str) -> dict:
    """Get worktree entry by name. Raises click.Abort on not found."""
    import click
    try:
        resp = api_request("GET", "/api/dev-worktree/by-name", params={"name": name})
        return resp.json()
    except Exception:
        registry = _load_local_registry()
        if name not in registry:
            click.echo(f"Worktree '{name}' not found. Use `y dev wt list` to see available worktrees.", err=True)
            raise click.Abort()
        return registry[name]


def create_worktree(name: str, project_path: str, worktree_path: str, branch: str, todo_id: str = None) -> dict:
    """Create a worktree via API, fallback to local JSON."""
    body = {
        "name": name,
        "project_path": project_path,
        "worktree_path": worktree_path,
        "branch": branch,
    }
    if todo_id:
        body["todo_id"] = todo_id
    try:
        resp = api_request("POST", "/api/dev-worktree", json=body)
        return resp.json()
    except Exception:
        registry = _load_local_registry()
        registry[name] = body
        _save_local_registry(registry)
        return registry[name]


def remove_worktree(name: str):
    """Remove a worktree via API, fallback to local JSON."""
    try:
        # Get worktree_id by name first
        resp = api_request("GET", "/api/dev-worktree/by-name", params={"name": name})
        wt = resp.json()
        api_request("POST", "/api/dev-worktree/remove", json={"worktree_id": wt["worktree_id"]})
    except Exception:
        registry = _load_local_registry()
        if name in registry:
            del registry[name]
            _save_local_registry(registry)


def update_worktree(name: str, **fields):
    """Update fields on an existing worktree entry."""
    try:
        resp = api_request("GET", "/api/dev-worktree/by-name", params={"name": name})
        wt = resp.json()
        api_request("POST", "/api/dev-worktree/update", json={"worktree_id": wt["worktree_id"], **fields})
    except Exception:
        registry = _load_local_registry()
        if name in registry:
            registry[name].update(fields)
            _save_local_registry(registry)


def server_sync(name: str, server_state: dict):
    """Sync server state (PIDs, ports, domains) to registry."""
    update_worktree(name, server_state=server_state)
