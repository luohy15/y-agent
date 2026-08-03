"""`y module delete <slug>` — hard-delete a module and all of its versions."""

from __future__ import annotations

import click
import httpx

from ._api import delete_module, resolve_module
from ._paths import meta_path, source_path, ui_dir, validate_slug


@click.command("delete")
@click.argument("slug")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt")
def module_delete(slug, yes):
    """Delete a module and its version history. This does not touch the
    authoring source on the VM."""
    try:
        slug = validate_slug(slug)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    module = resolve_module(slug)
    if not module:
        raise click.ClickException(f"unknown module {slug!r}")

    if not yes and not click.confirm(
        f"Delete module {slug!r} and all of its published versions? This cannot be undone."
    ):
        raise click.Abort()

    try:
        result = delete_module(module["module_id"])
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = str(exc.response.json().get("detail", ""))
        except Exception:
            detail = exc.response.text[:200]
        raise click.ClickException(
            f"delete failed: {exc.response.status_code} {detail}"
        ) from exc

    click.echo(
        f"Deleted {slug} ({result.get('deleted_versions', 0)} version(s) removed)"
    )
    click.echo("Authoring source was left untouched:")
    click.echo(f"  {source_path(slug)}")
    click.echo(f"  {meta_path(slug)}")
    parts_dir = ui_dir() / slug
    if parts_dir.is_dir():
        click.echo(f"  {parts_dir}/")
