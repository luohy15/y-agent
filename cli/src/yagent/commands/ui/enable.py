"""`y ui enable <slug>` / `y ui disable <slug>`."""

from __future__ import annotations

import click
import httpx

from ._api import resolve_artifact, set_enabled
from ._paths import validate_slug


def _toggle(slug: str, enabled: bool) -> None:
    try:
        slug = validate_slug(slug)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    artifact = resolve_artifact(slug)
    if not artifact:
        raise click.ClickException(f"unknown artifact {slug!r}")

    try:
        updated = set_enabled(artifact["artifact_id"], enabled)
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = str(exc.response.json().get("detail", ""))
        except Exception:
            detail = exc.response.text[:200]
        raise click.ClickException(
            f"{'enable' if enabled else 'disable'} failed: "
            f"{exc.response.status_code} {detail}"
        ) from exc

    state = "enabled" if updated.get("enabled") else "disabled"
    click.echo(f"{slug} is now {state}")


@click.command("enable")
@click.argument("slug")
def ui_enable(slug):
    """Show the artifact in the host panel list."""
    _toggle(slug, True)


@click.command("disable")
@click.argument("slug")
def ui_disable(slug):
    """Hide the artifact without deleting history."""
    _toggle(slug, False)
