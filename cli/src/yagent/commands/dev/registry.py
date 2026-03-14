"""Worktree registry: tracks managed worktrees in ~/.y-agent/dev-worktrees.json"""
import json
import os


def _registry_path() -> str:
    home = os.path.expanduser(os.getenv("Y_AGENT_HOME", "~/.y-agent"))
    return os.path.join(home, "dev-worktrees.json")


def load_registry() -> dict[str, dict]:
    """Load registry. Returns {name: {project_path, worktree_path, branch}}."""
    path = _registry_path()
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save_registry(registry: dict[str, dict]):
    path = _registry_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(registry, f, indent=2)


def get_worktree(name: str) -> dict:
    """Get worktree entry by name. Raises click.Abort on not found."""
    import click
    registry = load_registry()
    if name not in registry:
        click.echo(f"Worktree '{name}' not found. Use `y dev wt list` to see available worktrees.", err=True)
        raise click.Abort()
    return registry[name]
