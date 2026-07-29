"""`y ui list` — owner's artifacts with active version."""

from __future__ import annotations

import click

from ._api import list_artifacts


@click.command("list")
@click.option("--enabled-only", is_flag=True, help="Hide disabled artifacts")
def ui_list(enabled_only):
    """List UI artifacts for the current user."""
    artifacts = list_artifacts(enabled_only=enabled_only)
    if not artifacts:
        click.echo("No UI artifacts.")
        return
    for a in artifacts:
        active = a.get("active_version") or {}
        version_no = active.get("version_no")
        label = active.get("label") or a.get("slug")
        enabled = "on" if a.get("enabled", True) else "off"
        ver = f"v{version_no}" if version_no is not None else "-"
        click.echo(
            f"  {a['slug']:20} {ver:6} "
            f"enabled={enabled:3}  {label}"
        )
