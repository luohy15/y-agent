"""`y module rollback <slug>` — repoint to the previous version (no rebuild)."""

from __future__ import annotations

import click
import httpx

from ._api import resolve_module, rollback
from ._paths import validate_slug


@click.command("rollback")
@click.argument("slug")
def module_rollback(slug):
    """Repoint the active version to the previous one."""
    try:
        slug = validate_slug(slug)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    module = resolve_module(slug)
    if not module:
        raise click.ClickException(f"unknown module {slug!r}")

    try:
        updated = rollback(module["module_id"])
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = str(exc.response.json().get("detail", ""))
        except Exception:
            detail = exc.response.text[:200]
        raise click.ClickException(
            f"rollback failed: {exc.response.status_code} {detail}"
        ) from exc

    click.echo(
        f"Rolled back {slug}; active_version_id={updated.get('active_version_id')}"
    )
