"""`y module create <slug>` — scaffold source + materialize SDK (decision D5/D7)."""

from __future__ import annotations

import json
import shutil
import sys

import click
import httpx

from ._api import create_module, resolve_module
from ._paths import meta_path, source_dir, source_path, ui_dir, validate_slug
from ._sdk import ensure_sdk, package_sdk_root


@click.command("create")
@click.argument("slug")
@click.option("--label", default=None, help="Sidebar label (default: title-cased slug)")
@click.option("--icon", default="box", show_default=True, help="Sidebar icon key")
@click.option("--force", is_flag=True, help="Overwrite existing source/meta files")
@click.option(
    "--no-register",
    is_flag=True,
    help="Scaffold locally only; skip POST /api/module/create",
)
def module_create(slug, label, icon, force, no_register):
    """Scaffold a starter module under $Y_AGENT_HOME/modules/ and bootstrap the SDK."""
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
            f"module {slug!r} already exists ({source_dir(slug)}); use --force to overwrite"
        )

    templates = package_sdk_root() / "templates"
    ui_dir(slug).mkdir(parents=True, exist_ok=True)
    shutil.copy2(templates / "starter.tsx", src)

    meta_body = {
        "label": label or slug.replace("-", " ").replace("_", " ").title(),
        "icon": icon,
        "description": "",
        "parts": ["ui"],
        "min_backend_version": None,
    }
    meta.write_text(json.dumps(meta_body, indent=2) + "\n", encoding="utf-8")

    module_id = None
    if not no_register:
        try:
            existing = resolve_module(slug)
            if existing:
                module_id = existing["module_id"]
                click.echo(f"Already registered: {slug} ({module_id})")
            else:
                created = create_module(slug)
                module_id = created["module_id"]
                click.echo(f"Registered: {slug} ({module_id})")
        except httpx.HTTPStatusError as exc:
            # S3 may not have shipped POST /api/module/create yet; local scaffold still succeeds.
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
    click.echo(f"Edit the source, then: y module publish {slug}")


def _http_detail(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
        if isinstance(body, dict) and "detail" in body:
            return str(body["detail"])
    except Exception:
        pass
    return (exc.response.text or "")[:200]
