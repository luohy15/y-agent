"""`y ui create <slug>` — scaffold source + materialize SDK (decision D5/D7)."""

from __future__ import annotations

import json
import shutil
import sys

import click
import httpx

from ._api import create_artifact, resolve_artifact
from ._paths import meta_path, source_path, ui_dir, validate_slug
from ._sdk import ensure_sdk, package_sdk_root


@click.command("create")
@click.argument("slug")
@click.option("--label", default=None, help="Sidebar label (default: title-cased slug)")
@click.option("--icon", default="box", show_default=True, help="Sidebar icon key")
@click.option("--force", is_flag=True, help="Overwrite existing source/meta files")
@click.option(
    "--no-register",
    is_flag=True,
    help="Scaffold locally only; skip POST /api/ui/create",
)
def ui_create(slug, label, icon, force, no_register):
    """Scaffold a starter artifact under $Y_AGENT_HOME/ui/ and bootstrap the SDK."""
    try:
        slug = validate_slug(slug)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        ensure_sdk()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    src = source_path(slug)
    meta = meta_path(slug)
    if (src.exists() or meta.exists()) and not force:
        raise click.ClickException(
            f"artifact {slug!r} already exists ({src.name} / {meta.name}); use --force to overwrite"
        )

    templates = package_sdk_root() / "templates"
    ui_dir().mkdir(parents=True, exist_ok=True)
    shutil.copy2(templates / "starter.tsx", src)

    meta_body = {
        "label": label or slug.replace("-", " ").replace("_", " ").title(),
        "icon": icon,
    }
    meta.write_text(json.dumps(meta_body, indent=2) + "\n", encoding="utf-8")

    artifact_id = None
    if not no_register:
        try:
            existing = resolve_artifact(slug)
            if existing:
                artifact_id = existing["artifact_id"]
                click.echo(f"Already registered: {slug} ({artifact_id})")
            else:
                created = create_artifact(slug)
                artifact_id = created["artifact_id"]
                click.echo(f"Registered: {slug} ({artifact_id})")
        except httpx.HTTPStatusError as exc:
            # S3 may not have shipped POST /api/ui/create yet; local scaffold still succeeds.
            detail = _http_detail(exc)
            click.echo(
                f"Warning: could not register with API ({exc.response.status_code}: {detail}). "
                "Local files were written; publish will retry registration.",
                err=True,
            )
        except (httpx.HTTPError, SystemExit) as exc:
            # Not logged in / network: still leave the scaffold.
            click.echo(
                f"Warning: could not register with API ({exc}). Local files were written.",
                err=True,
            )

    click.echo(f"Created {src}")
    click.echo(f"         {meta}")
    click.echo(f"Edit the source, then: y ui publish {slug}")


def _http_detail(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
        if isinstance(body, dict) and "detail" in body:
            return str(body["detail"])
    except Exception:
        pass
    return (exc.response.text or "")[:200]
