"""Thin helpers over /api/ui/* for the CLI."""

from __future__ import annotations

from typing import Any, Optional

from yagent.api_client import api_request


def list_artifacts(enabled_only: bool = False) -> list[dict]:
    params = {"enabled_only": "true"} if enabled_only else {}
    return api_request("GET", "/api/ui/list", params=params).json()


def list_versions(artifact_id: str) -> list[dict]:
    return api_request(
        "GET", "/api/ui/versions", params={"artifact_id": artifact_id}
    ).json()


def create_artifact(slug: str, kind: str = "panel") -> dict:
    """Register a new artifact row. Requires S3's POST /api/ui/create."""
    return api_request(
        "POST", "/api/ui/create", json={"slug": slug, "kind": kind}
    ).json()


def resolve_artifact(slug: str) -> Optional[dict]:
    for artifact in list_artifacts(enabled_only=False):
        if artifact.get("slug") == slug:
            return artifact
    return None


def resolve_or_create(slug: str) -> dict:
    existing = resolve_artifact(slug)
    if existing:
        return existing
    return create_artifact(slug)


def publish_bundle(
    *,
    artifact_id: str,
    bundle_bytes: bytes,
    sha256: str,
    label: Optional[str],
    icon: Optional[str],
    min_host_version: int,
    source_digest: str,
    activate: bool,
) -> dict:
    files = {
        "file": ("bundle.js", bundle_bytes, "text/javascript"),
    }
    data: dict[str, Any] = {
        "artifact_id": artifact_id,
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
    return api_request("POST", "/api/ui/publish", files=files, data=data).json()


def rollback(artifact_id: str) -> dict:
    return api_request(
        "POST", "/api/ui/rollback", json={"artifact_id": artifact_id}
    ).json()


def activate(artifact_id: str, version_no: int) -> dict:
    return api_request(
        "POST",
        "/api/ui/activate",
        json={"artifact_id": artifact_id, "version_no": version_no},
    ).json()


def set_enabled(artifact_id: str, enabled: bool) -> dict:
    return api_request(
        "POST",
        "/api/ui/enable",
        json={"artifact_id": artifact_id, "enabled": enabled},
    ).json()


def delete_artifact(artifact_id: str) -> dict:
    return api_request(
        "POST", "/api/ui/delete", json={"artifact_id": artifact_id}
    ).json()
