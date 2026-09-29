"""Worktree registry: the API is the only source of truth."""
import click
import httpx

from yagent.api_client import api_request


def _call(method: str, path: str, **kwargs) -> httpx.Response:
    try:
        return api_request(method, path, **kwargs)
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        raise click.ClickException(f"dev-worktree API error: {exc}")


def _by_name(name: str) -> dict | None:
    """Look up an active worktree by name; None when the API answers 404."""
    try:
        return api_request("GET", "/api/dev-worktree/by-name", params={"name": name}).json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise click.ClickException(f"dev-worktree API error: {exc}")
    except httpx.RequestError as exc:
        raise click.ClickException(f"dev-worktree API error: {exc}")


def load_registry() -> dict[str, dict]:
    """Load all worktrees as {name: {...}}."""
    resp = _call("GET", "/api/dev-worktree/list", params={"status": "active"})
    return {w["name"]: w for w in resp.json()}


def get_worktree(name: str) -> dict:
    """Get worktree entry by name. Raises click.Abort on not found."""
    wt = _by_name(name)
    if wt is None:
        click.echo(f"Worktree '{name}' not found. Use `y dev wt list` to see available worktrees.", err=True)
        raise click.Abort()
    return wt


def create_worktree(name: str, project_path: str, worktree_path: str, branch: str, todo_id: str = None) -> dict:
    """Create a worktree via API."""
    body = {
        "name": name,
        "project_path": project_path,
        "worktree_path": worktree_path,
        "branch": branch,
    }
    if todo_id:
        body["todo_id"] = todo_id
    return _call("POST", "/api/dev-worktree", json=body).json()


def remove_worktree(name: str):
    """Remove a worktree via API; a missing entry is a no-op."""
    wt = _by_name(name)
    if wt is not None:
        _call("POST", "/api/dev-worktree/remove", json={"worktree_id": wt["worktree_id"]})


def update_worktree(name: str, **fields):
    """Update fields on an existing worktree entry; a missing entry is a no-op."""
    wt = _by_name(name)
    if wt is not None:
        _call("POST", "/api/dev-worktree/update", json={"worktree_id": wt["worktree_id"], **fields})


def server_sync(name: str, server_state: dict):
    """Sync server state (PIDs, ports, domains) to registry."""
    update_worktree(name, server_state=server_state)
