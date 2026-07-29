"""`y ui activate <slug> <n>` — promote a historical version by number."""

from __future__ import annotations

import click
import httpx

from ._api import activate, resolve_artifact
from ._paths import validate_slug


@click.command("activate")
@click.argument("slug")
@click.argument("version_no", type=int)
def ui_activate(slug, version_no):
    """Activate a historical version by its version number."""
    try:
        slug = validate_slug(slug)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    artifact = resolve_artifact(slug)
    if not artifact:
        raise click.ClickException(f"unknown artifact {slug!r}")

    try:
        updated = activate(artifact["artifact_id"], version_no)
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = str(exc.response.json().get("detail", ""))
        except Exception:
            detail = exc.response.text[:200]
        raise click.ClickException(
            f"activate failed: {exc.response.status_code} {detail}"
        ) from exc

    click.echo(
        f"Activated {slug} v{version_no}; "
        f"active_version_id={updated.get('active_version_id')}"
    )
