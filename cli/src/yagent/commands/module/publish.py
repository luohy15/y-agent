"""`y module publish <slug>` — build on the VM and POST the bundle to the API."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import click
import httpx

from ._api import publish_bundle, resolve_or_create
from ._build import build_artifact
from ._paths import meta_path, validate_slug
from ._sdk import load_contract


def _compose_description(desc: Optional[str], trace_id: Optional[str]) -> Optional[str]:
    """Compose the stored description from --desc and Y_TRACE_ID (plan 2991 D2).

    trace_id set + desc given -> "[<trace_id>] <desc>"
    trace_id set + desc absent -> "[<trace_id>]"
    trace_id unset + desc given -> "<desc>"
    trace_id unset + desc absent -> None
    """
    if trace_id:
        tag = f"[{trace_id}]"
        return f"{tag} {desc}" if desc else tag
    return desc


@click.command("publish")
@click.argument("slug")
@click.option(
    "--no-activate",
    is_flag=True,
    help="Stage a version without making it active (PRD story 7)",
)
@click.option("--label", default=None, help="Override sidebar label from <slug>.json")
@click.option("--icon", default=None, help="Override sidebar icon from <slug>.json")
@click.option("-d", "--desc", default=None, help="Description/tag for this version, auto-prefixed with [Y_TRACE_ID]")
def module_publish(slug, no_activate, label, icon, desc):
    """Build the module and publish it. A build error leaves the active version untouched."""
    try:
        slug = validate_slug(slug)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    description = _compose_description(desc, os.environ.get("Y_TRACE_ID"))

    meta = _load_meta(slug)
    label = label if label is not None else meta.get("label")
    icon = icon if icon is not None else meta.get("icon")

    try:
        manifest = build_artifact(slug)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    except RuntimeError as exc:
        # Print compiler diagnostics and exit non-zero without touching the API.
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    contract = load_contract()
    min_host_version = int(
        manifest.get("min_host_version") or contract.get("version") or 1
    )

    try:
        module = resolve_or_create(slug)
    except httpx.HTTPStatusError as exc:
        detail = _http_detail(exc)
        raise click.ClickException(
            f"could not resolve/create module {slug!r}: "
            f"{exc.response.status_code} {detail}"
        ) from exc

    bundle_path = Path(manifest["bundle"])
    bundle_bytes = bundle_path.read_bytes()

    try:
        version = publish_bundle(
            module_id=module["module_id"],
            bundle_bytes=bundle_bytes,
            sha256=manifest["sha256"],
            label=label,
            icon=icon,
            min_host_version=min_host_version,
            source_digest=manifest["source_digest"],
            description=description,
            activate=not no_activate,
        )
    except httpx.HTTPStatusError as exc:
        detail = _http_detail(exc)
        raise click.ClickException(
            f"publish failed: {exc.response.status_code} {detail}"
        ) from exc

    state = "staged" if no_activate else "active"
    click.echo(
        f"Published {slug} v{version['version_no']} ({state}) "
        f"sha256={version['ui_sha256'][:12]}… "
        f"({manifest['bytes']} bytes)"
    )


def _load_meta(slug: str) -> dict:
    path = meta_path(slug)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"invalid metadata file {path}: {exc}") from exc


def _http_detail(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
        if isinstance(body, dict) and "detail" in body:
            return str(body["detail"])
    except Exception:
        pass
    return (exc.response.text or "")[:200]
