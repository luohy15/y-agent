"""`y module list` — owner's modules with active version."""

from __future__ import annotations

import click

from ._api import list_modules


@click.command("list")
@click.option("--enabled-only", is_flag=True, help="Hide disabled modules")
def module_list(enabled_only):
    """List modules for the current user."""
    modules = list_modules(enabled_only=enabled_only)
    if not modules:
        click.echo("No modules.")
        return
    for m in modules:
        active = m.get("active_version") or {}
        version_no = active.get("version_no")
        label = active.get("label") or m.get("slug")
        enabled = "on" if m.get("enabled", True) else "off"
        ver = f"v{version_no}" if version_no is not None else "-"
        click.echo(
            f"  {m['slug']:20} {ver:6} "
            f"enabled={enabled:3}  {label}"
        )
