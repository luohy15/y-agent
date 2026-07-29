"""ui artifact controller (todo 2412, S3).

The API owns the bundle write: the CLI builds locally and POSTs bytes, the
server recomputes sha256 (the client's claimed hash is never trusted) and
writes the content-addressed object under the ui/ prefix. Artifact code is
never executed here; label/icon arrive as plain form fields. When
Y_AGENT_S3_BUCKET is unset (local dev) bundles are written to a local
directory with the same keys.

Publish order is verify-ownership -> write bundle -> insert version row:
the key is content-addressed so an orphaned object is harmless, whereas an
orphaned active pointer is a broken panel.
"""

import hashlib
import os
import re
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from storage.dto.ui_artifact import UiArtifact
from storage.service import ui_artifact as ui_service

router = APIRouter(prefix="/ui")

S3_BUCKET = os.environ.get("Y_AGENT_S3_BUCKET", "")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
ALLOWED_KINDS = {"panel"}


class CreateRequest(BaseModel):
    slug: str
    kind: str = "panel"


class ArtifactActionRequest(BaseModel):
    artifact_id: Optional[str] = None
    slug: Optional[str] = None


class ActivateRequest(BaseModel):
    artifact_id: Optional[str] = None
    slug: Optional[str] = None
    version_no: int


class EnableRequest(BaseModel):
    artifact_id: Optional[str] = None
    slug: Optional[str] = None
    enabled: bool


def _bundle_dir() -> Path:
    return Path(
        os.environ.get(
            "Y_AGENT_UI_BUNDLE_DIR",
            str(Path.home() / ".y-agent" / "ui-bundles"),
        )
    )


def _write_bundle(storage_key: str, content: bytes) -> None:
    if S3_BUCKET:
        boto3.client("s3").put_object(
            Bucket=S3_BUCKET,
            Key=storage_key,
            Body=content,
            ContentType="text/javascript",
        )
        return
    base = _bundle_dir().resolve()
    path = (base / storage_key).resolve()
    if base != path and base not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid storage key")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _read_bundle(storage_key: str) -> bytes:
    if S3_BUCKET:
        try:
            obj = boto3.client("s3").get_object(Bucket=S3_BUCKET, Key=storage_key)
            return obj["Body"].read()
        except ClientError as exc:
            raise HTTPException(status_code=404, detail="Bundle not found") from exc
    path = _bundle_dir() / storage_key
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Bundle not found")
    return path.read_bytes()


def _resolve_artifact(user_id: int, artifact_id: Optional[str], slug: Optional[str]) -> UiArtifact:
    """Pointer-move endpoints accept either artifact_id or slug so the CLI
    avoids a /list round trip."""
    if artifact_id:
        artifact = ui_service.get_artifact(user_id, artifact_id)
    elif slug:
        artifact = ui_service.get_artifact_by_slug(user_id, slug)
    else:
        raise HTTPException(status_code=400, detail="artifact_id or slug is required")
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


@router.post("/create")
async def create_artifact(req: CreateRequest, request: Request):
    """Mint an artifact row. Idempotent by slug, so a re-run of `y ui create` is safe."""
    user_id = _get_user_id(request)
    if not SLUG_RE.match(req.slug):
        raise HTTPException(status_code=400, detail="Invalid slug")
    if req.kind not in ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail="Invalid kind")
    artifact = ui_service.create_artifact(user_id, req.slug, kind=req.kind)
    return artifact.to_dict()


@router.get("/list")
async def list_artifacts(request: Request, enabled_only: bool = Query(False)):
    """Owner's artifacts with the active version joined in."""
    user_id = _get_user_id(request)
    artifacts = ui_service.list_artifacts(user_id, enabled_only=enabled_only)
    result = []
    for artifact in artifacts:
        data = artifact.to_dict()
        active = None
        if artifact.active_version_id:
            active = ui_service.get_version(user_id, artifact.active_version_id)
        data["active_version"] = active.to_dict() if active else None
        result.append(data)
    return result


@router.get("/versions")
async def list_versions(
    request: Request,
    artifact_id: Optional[str] = Query(None),
    slug: Optional[str] = Query(None),
):
    user_id = _get_user_id(request)
    artifact = _resolve_artifact(user_id, artifact_id, slug)
    versions = ui_service.list_versions(user_id, artifact.artifact_id)
    return [v.to_dict() for v in versions]


@router.post("/publish")
async def publish(
    request: Request,
    file: UploadFile,
    artifact_id: str = Form(...),
    sha256: str = Form(...),
    label: Optional[str] = Form(None),
    icon: Optional[str] = Form(None),
    min_host_version: int = Form(1),
    source_digest: Optional[str] = Form(None),
    activate: bool = Form(True),
):
    user_id = _get_user_id(request)
    # Ownership check must precede the bundle write: storage_key is built from
    # the client-supplied artifact_id.
    if not ui_service.get_artifact(user_id, artifact_id):
        raise HTTPException(status_code=404, detail="Artifact not found")
    content = await file.read()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != sha256.strip().lower():
        raise HTTPException(status_code=400, detail="sha256 mismatch")
    storage_key = f"ui/{artifact_id}/{actual_sha256}.js"
    _write_bundle(storage_key, content)
    version = ui_service.publish(
        user_id,
        artifact_id,
        sha256=actual_sha256,
        storage_key=storage_key,
        label=label,
        icon=icon,
        min_host_version=min_host_version,
        source_digest=source_digest,
        activate=activate,
    )
    if not version:
        # Defence in depth; the ownership check above already covers this.
        raise HTTPException(status_code=404, detail="Artifact not found")
    return version.to_dict()


@router.post("/rollback")
async def rollback(req: ArtifactActionRequest, request: Request):
    user_id = _get_user_id(request)
    artifact = _resolve_artifact(user_id, req.artifact_id, req.slug)
    updated = ui_service.rollback(user_id, artifact.artifact_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Nothing to roll back to")
    return updated.to_dict()


@router.post("/activate")
async def activate(req: ActivateRequest, request: Request):
    user_id = _get_user_id(request)
    artifact = _resolve_artifact(user_id, req.artifact_id, req.slug)
    updated = ui_service.activate(user_id, artifact.artifact_id, req.version_no)
    if not updated:
        raise HTTPException(status_code=404, detail="Version not found")
    return updated.to_dict()


@router.post("/enable")
async def set_enabled(req: EnableRequest, request: Request):
    user_id = _get_user_id(request)
    artifact = _resolve_artifact(user_id, req.artifact_id, req.slug)
    updated = ui_service.set_enabled(user_id, artifact.artifact_id, req.enabled)
    if not updated:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return updated.to_dict()


@router.get("/artifact/{version_id}/bundle")
async def get_bundle(version_id: str, request: Request):
    user_id = _get_user_id(request)
    version = ui_service.get_version(user_id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    content = _read_bundle(version.storage_key)
    # Bundles are content-addressed and versions immutable, so cache forever.
    return Response(
        content=content,
        media_type="text/javascript",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
