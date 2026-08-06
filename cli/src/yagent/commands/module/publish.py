"""`y module publish <slug>` — build UI + API halves and POST them atomically."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import click
import httpx

from ._api import publish_bundle, resolve_or_create
from ._build import build_api_bundle, build_artifact
from ._paths import meta_path, source_path, validate_slug
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
@click.option("--label", default=None, help="Override sidebar label from module.json")
@click.option("--icon", default=None, help="Override sidebar icon from module.json")
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
    min_backend_version = meta.get("min_backend_version")
    if min_backend_version is not None:
        try:
            min_backend_version = int(min_backend_version)
        except (TypeError, ValueError) as exc:
            raise click.ClickException(
                f"module.json min_backend_version must be an int, got {min_backend_version!r}"
            ) from exc
    dispatch_scope = meta.get("dispatch", "maintainer")
    if dispatch_scope not in {"maintainer", "authenticated"}:
        raise click.ClickException(
            "module.json dispatch must be 'maintainer' or 'authenticated', "
            f"got {dispatch_scope!r}"
        )

    has_ui = source_path(slug).is_file()
    ui_manifest = None
    api_manifest = None

    if has_ui:
        try:
            ui_manifest = build_artifact(slug)
        except FileNotFoundError as exc:
            raise click.ClickException(str(exc)) from exc
        except RuntimeError as exc:
            # Print compiler diagnostics and exit non-zero without touching the API.
            print(str(exc), file=sys.stderr)
            sys.exit(1)

    try:
        api_manifest = build_api_bundle(slug)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    if ui_manifest is None and api_manifest is None:
        raise click.ClickException(
            f"module {slug!r} has neither ui/index.tsx nor api.py; nothing to publish"
        )

    contract = load_contract()
    min_host_version = int(
        (ui_manifest or {}).get("min_host_version") or contract.get("version") or 1
    )

    try:
        module = resolve_or_create(slug)
    except httpx.HTTPStatusError as exc:
        detail = _http_detail(exc)
        raise click.ClickException(
            f"could not resolve/create module {slug!r}: "
            f"{exc.response.status_code} {detail}"
        ) from exc

    ui_bytes = None
    ui_sha = None
    source_digest = None
    if ui_manifest is not None:
        ui_bytes = Path(ui_manifest["bundle"]).read_bytes()
        ui_sha = ui_manifest["sha256"]
        source_digest = ui_manifest.get("source_digest")

    api_bytes = None
    api_sha = None
    if api_manifest is not None:
        api_bytes = Path(api_manifest["bundle"]).read_bytes()
        api_sha = api_manifest["sha256"]

    try:
        version = publish_bundle(
            module_id=module["module_id"],
            bundle_bytes=ui_bytes,
            sha256=ui_sha,
            api_bundle_bytes=api_bytes,
            api_sha256=api_sha,
            label=label,
            icon=icon,
            min_host_version=min_host_version,
            source_digest=source_digest,
            description=description,
            activate=not no_activate,
            min_backend_version=min_backend_version,
            dispatch_scope=dispatch_scope,
        )
    except httpx.HTTPStatusError as exc:
        detail = _http_detail(exc)
        raise click.ClickException(
            f"publish failed: {exc.response.status_code} {detail}"
        ) from exc

    state = "staged" if no_activate else "active"
    parts = []
    if version.get("ui_sha256"):
        parts.append(f"ui={version['ui_sha256'][:12]}…")
    if version.get("api_sha256"):
        parts.append(f"api={version['api_sha256'][:12]}…")
    size_bits = []
    if ui_manifest is not None:
        size_bits.append(f"ui {ui_manifest['bytes']}B")
    if api_manifest is not None:
        size_bits.append(f"api {api_manifest['bytes']}B")
    click.echo(
        f"Published {slug} v{version['version_no']} ({state}) "
        f"{' '.join(parts)} ({', '.join(size_bits)})"
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
