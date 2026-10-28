"""`y module publish <slug>` — build UI + API halves and POST them atomically."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import click
import httpx

from storage.service.module_icon import normalize_module_icon

from ._api import publish_bundle, resolve_or_create
from ._build import build_api_bundle, build_artifact
from ._paths import meta_path, source_dir, source_path, ui_dir, validate_slug
from ._sdk import load_contract
from ._source import find_icon_conflict, verify_source_snapshot


VALID_SURFACES = {"panel", "detail", "shell"}
_SOURCE_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _validate_source_sha(ctx, param, value):
    if not isinstance(value, str) or not _SOURCE_SHA_RE.fullmatch(value):
        raise click.BadParameter(
            "must be the full 40-hex lowercase SHA of the approved origin/main tip"
        )
    return value


def _validate_surfaces(surfaces) -> str:
    """module.json 'surfaces' -> the comma list the API expects, deduped in order.

    Mirrors the dispatch_scope validation below: reject anything outside
    {panel, detail, shell} up front, before a build even starts.
    """
    if not isinstance(surfaces, list) or not surfaces:
        raise click.ClickException(
            f"module.json surfaces must be a non-empty list, got {surfaces!r}"
        )
    seen: list[str] = []
    for s in surfaces:
        if not isinstance(s, str) or s not in VALID_SURFACES:
            raise click.ClickException(
                "module.json surfaces must only contain 'panel', 'detail', 'shell', "
                f"got {s!r}"
            )
        if s not in seen:
            seen.append(s)
    return ",".join(seen)


@click.command("publish")
@click.argument("slug")
@click.option(
    "--no-activate",
    is_flag=True,
    help="Stage a version without making it active (PRD story 7)",
)
@click.option("--label", default=None, help="Override sidebar label from module.json")
@click.option("--icon", default=None, help="Override sidebar icon from module.json")
@click.option("-d", "--desc", default=None, help="Description/tag for this version")
@click.option(
    "--trace-id",
    default=None,
    help="Trace/todo id for this version, defaults to $Y_TRACE_ID",
)
@click.option(
    "--source-sha",
    required=True,
    callback=_validate_source_sha,
    help="Full 40-hex SHA of the approved origin/main tip. Refused if it is not the live tip.",
)
def module_publish(slug, no_activate, label, icon, desc, trace_id, source_sha):
    """Build the module and publish it. A build error leaves the active version untouched."""
    try:
        slug = validate_slug(slug)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    trace_id = trace_id or os.environ.get("Y_TRACE_ID") or None
    # Before metadata and either build: a mismatch must not start a build.
    verify_source_snapshot(slug, source_sha)

    meta = _load_meta(slug)
    label = label if label is not None else meta.get("label")
    icon = checked_icon(slug, icon if icon is not None else meta.get("icon"))
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
    ui_surfaces = _validate_surfaces(meta.get("surfaces", ["panel"]))
    from storage.service.module_carrier import CarrierConflict, dump_tag_carriers, parse_tag_carriers

    try:
        tag_carriers = dump_tag_carriers(parse_tag_carriers(meta.get("tag_carriers", [])))
    except CarrierConflict as exc:
        raise click.ClickException(str(exc)) from exc
    contract = load_contract()

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

    min_host_version = int(
        (ui_manifest or {}).get("min_host_version") or contract.get("version") or 1
    )

    # Source can change while the builds run. Recheck before any API call.
    verify_source_snapshot(slug, source_sha)

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
            description=desc,
            trace_id=trace_id,
            activate=not no_activate,
            min_backend_version=min_backend_version,
            dispatch_scope=dispatch_scope,
            ui_surfaces=ui_surfaces,
            tag_carriers=tag_carriers,
            source_commit=source_sha,
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
        f"{' '.join(parts)} ({', '.join(size_bits)}) src={source_sha[:12]}"
    )


def checked_icon(slug: str, raw, root=None) -> str:
    """Resolve an icon and reject a missing value, ``box``, or a sibling clash.

    ``root`` defaults to the canonical module source root. The clash check uses
    the normalized value, so two SVG files that differ only by whitespace or
    ``width``/``height`` still conflict. Runs before either publish build.
    """
    if not isinstance(raw, str) or raw == "":
        raise click.ClickException(
            'module icon is required: set module.json "icon" or pass --icon '
            "(a registry key, or a ui/*.svg path)"
        )
    resolved = _resolve_icon(slug, raw)
    holder = find_icon_conflict(slug, resolved, root=root)
    if holder:
        raise click.ClickException(f"module icon is already used by {holder}")
    return resolved


def _resolve_icon(slug: str, raw: str) -> str:
    """Registry key, or a ui/*.svg path read and normalized.

    ``--icon`` and module.json share this. ``box`` is rejected: it is only the
    host fallback for an unknown legacy value.
    """
    if not isinstance(raw, str) or raw == "":
        raise click.ClickException(
            f"module icon must be a registry key or a ui/*.svg path, got {raw!r}"
        )
    if raw.endswith(".svg"):
        return _read_svg_icon(slug, raw)
    if raw == "box":
        raise click.ClickException(
            "module icon 'box' is not allowed; it is only the rendering fallback "
            "for an unknown legacy value"
        )
    valid_icons = load_contract()["icons"]
    if raw not in valid_icons:
        raise click.ClickException(
            f"module icon must be one of {', '.join(valid_icons)}, or a ui/*.svg path, got {raw!r}"
        )
    return raw


def _read_svg_icon(slug: str, raw: str) -> str:
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts:
        raise click.ClickException(
            f"module icon SVG must be a relative path under ui/, got {raw!r}"
        )
    root = source_dir(slug).resolve()
    ui = ui_dir(slug).resolve()
    full = (root / rel).resolve()
    try:
        full.relative_to(ui)
    except ValueError as exc:
        raise click.ClickException(
            f"module icon SVG must live under ui/, got {raw!r}"
        ) from exc
    if not full.is_file():
        raise click.ClickException(f"module icon SVG not found: {raw}")
    try:
        return normalize_module_icon(full.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except OSError as exc:
        raise click.ClickException(f"module icon SVG not readable: {raw}") from exc


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
