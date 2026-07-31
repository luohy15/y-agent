"""`y ui versions <slug>` — version history with the active version marked."""

from __future__ import annotations

import click

from ._api import list_versions, resolve_artifact
from ._paths import validate_slug


@click.command("versions")
@click.argument("slug")
def ui_versions(slug):
    """List version history for an artifact."""
    try:
        slug = validate_slug(slug)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    artifact = resolve_artifact(slug)
    if not artifact:
        raise click.ClickException(f"unknown artifact {slug!r}")

    versions = list_versions(artifact["artifact_id"])
    if not versions:
        click.echo(f"No versions for {slug}.")
        return

    active_id = artifact.get("active_version_id")
    # API returns newest first (service list is descending).
    for v in versions:
        mark = "*" if v.get("version_id") == active_id else " "
        label = v.get("label") or ""
        built = v.get("built_at") or v.get("created_at") or ""
        description = v.get("description") or ""
        line = f" {mark} v{v['version_no']:<4} {v['sha256'][:12]}…  {label:16} {built}"
        if description:
            line += f"  {description}"
        click.echo(line)
