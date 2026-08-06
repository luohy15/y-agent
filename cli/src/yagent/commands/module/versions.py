"""`y module versions <slug>` — version history with the active version marked."""

from __future__ import annotations

import click

from ._api import list_versions, resolve_module
from ._paths import validate_slug


@click.command("versions")
@click.argument("slug")
def module_versions(slug):
    """List version history for a module."""
    try:
        slug = validate_slug(slug)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    module = resolve_module(slug)
    if not module:
        raise click.ClickException(f"unknown module {slug!r}")

    versions = list_versions(module["module_id"])
    if not versions:
        click.echo(f"No versions for {slug}.")
        return

    active_id = module.get("active_version_id")
    # API returns newest first (service list is descending).
    for v in versions:
        mark = "*" if v.get("version_id") == active_id else " "
        label = v.get("label") or ""
        built = v.get("built_at") or v.get("created_at") or ""
        description = v.get("description") or ""
        sha = (v.get("ui_sha256") or "")[:12]
        # dispatch_scope is the only field that widens a version's audience past
        # the maintainer; show it so `y module versions` is the audit view.
        scope = v.get("dispatch_scope") or "maintainer"
        line = f" {mark} v{v['version_no']:<4} {sha}…  {scope:13} {label:16} {built}"
        if description:
            line += f"  {description}"
        click.echo(line)
