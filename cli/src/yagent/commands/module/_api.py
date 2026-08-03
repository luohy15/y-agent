"""Thin helpers over /api/module/* for the CLI."""

from __future__ import annotations

from typing import Any, Optional

from yagent.api_client import api_request


def list_modules(enabled_only: bool = False) -> list[dict]:
    params = {"enabled_only": "true"} if enabled_only else {}
    return api_request("GET", "/api/module/list", params=params).json()


def list_versions(module_id: str) -> list[dict]:
    return api_request(
        "GET", "/api/module/versions", params={"module_id": module_id}
    ).json()


def create_module(slug: str) -> dict:
    """Register a new module row. Requires S3's POST /api/module/create."""
    return api_request(
        "POST", "/api/module/create", json={"slug": slug}
    ).json()


def resolve_module(slug: str) -> Optional[dict]:
    for module in list_modules(enabled_only=False):
        if module.get("slug") == slug:
            return module
    return None


def resolve_or_create(slug: str) -> dict:
    existing = resolve_module(slug)
    if existing:
        return existing
    return create_module(slug)


def publish_bundle(
    *,
    module_id: str,
    bundle_bytes: bytes,
    sha256: str,
    label: Optional[str],
    icon: Optional[str],
    min_host_version: int,
    source_digest: str,
    activate: bool,
    min_backend_version: Optional[int] = None,
    description: Optional[str] = None,
) -> dict:
    files = {
        "file": ("bundle.js", bundle_bytes, "text/javascript"),
    }
    data: dict[str, Any] = {
        "module_id": module_id,
        "sha256": sha256,
        "min_host_version": str(min_host_version),
        "activate": "true" if activate else "false",
    }
    if label is not None:
        data["label"] = label
    if icon is not None:
        data["icon"] = icon
    if source_digest is not None:
        data["source_digest"] = source_digest
    if min_backend_version is not None:
        data["min_backend_version"] = str(min_backend_version)
    if description is not None:
        data["description"] = description
    return api_request("POST", "/api/module/publish", files=files, data=data).json()


def rollback(module_id: str) -> dict:
    return api_request(
        "POST", "/api/module/rollback", json={"module_id": module_id}
    ).json()


def activate(module_id: str, version_no: int) -> dict:
    return api_request(
        "POST",
        "/api/module/activate",
        json={"module_id": module_id, "version_no": version_no},
    ).json()


def set_enabled(module_id: str, enabled: bool) -> dict:
    return api_request(
        "POST",
        "/api/module/enable",
        json={"module_id": module_id, "enabled": enabled},
    ).json()


def delete_module(module_id: str) -> dict:
    return api_request(
        "POST", "/api/module/delete", json={"module_id": module_id}
    ).json()
