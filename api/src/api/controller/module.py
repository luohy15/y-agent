"""module controller (todo 2412 origin, renamed under todo 3020 phase 1).

The API owns the bundle write: the CLI builds locally and POSTs bytes, the
server recomputes sha256 (the client's claimed hash is never trusted) and
writes the content-addressed object under the module/ prefix. Module code is
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

from storage.dto.module import Module
from storage.service import module as module_service

router = APIRouter(prefix="/module")

S3_BUCKET = os.environ.get("Y_AGENT_S3_BUCKET", "")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

# D13: management endpoints below live on this router (registered before the
# raw-ASGI module dispatcher mounted at /api/module in a later phase), so a
# slug matching one of these names would collide with a management route.
RESERVED_SLUGS = {
    "create", "list", "versions", "publish", "rollback", "activate",
    "enable", "disable", "delete", "bundle", "schema-sql",
}


class CreateRequest(BaseModel):
    slug: str


class RollbackRequest(BaseModel):
    module_id: Optional[str] = None
    slug: Optional[str] = None
    # The version the caller saw fail. When given, the rollback is refused
    # with 409 if the active pointer has since moved (see
    # module.RollbackConflictError) instead of demoting whatever version
    # is active now.
    from_version_id: Optional[str] = None


class ActivateRequest(BaseModel):
    module_id: Optional[str] = None
    slug: Optional[str] = None
    version_no: int


class EnableRequest(BaseModel):
    module_id: Optional[str] = None
    slug: Optional[str] = None
    enabled: bool


class DeleteRequest(BaseModel):
    module_id: Optional[str] = None
    slug: Optional[str] = None


def _bundle_dir() -> Path:
    return Path(
        os.environ.get(
            "Y_AGENT_MODULE_BUNDLE_DIR",
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


def _delete_bundle(storage_key: str) -> None:
    """Best-effort: called after the owning rows are already gone, so a
    failure here just orphans bytes rather than leaving a broken row."""
    if S3_BUCKET:
        try:
            boto3.client("s3").delete_object(Bucket=S3_BUCKET, Key=storage_key)
        except Exception:
            # Anything (ClientError, a BotoCoreError, a credential failure)
            # must stay best-effort: the rows are already gone, so raising
            # here would turn an already-successful delete into a 500.
            pass
        return
    base = _bundle_dir().resolve()
    path = (base / storage_key).resolve()
    if base != path and base not in path.parents:
        return
    try:
        path.unlink()
    except OSError:
        pass


def _resolve_module(user_id: int, module_id: Optional[str], slug: Optional[str]) -> Module:
    """Pointer-move endpoints accept either module_id or slug so the CLI
    avoids a /list round trip."""
    if module_id:
        module = module_service.get_module(user_id, module_id)
    elif slug:
        module = module_service.get_module_by_slug(user_id, slug)
    else:
        raise HTTPException(status_code=400, detail="module_id or slug is required")
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    return module


@router.post("/create")
async def create_module(req: CreateRequest, request: Request):
    """Mint a module row. Idempotent by slug, so a re-run of `y module create` is safe."""
    user_id = _get_user_id(request)
    if not SLUG_RE.match(req.slug):
        raise HTTPException(status_code=400, detail="Invalid slug")
    if req.slug in RESERVED_SLUGS:
        raise HTTPException(status_code=400, detail="slug is reserved")
    module = module_service.create_module(user_id, req.slug)
    return module.to_dict()


@router.get("/list")
async def list_modules(request: Request, enabled_only: bool = Query(False)):
    """Owner's modules with the active version joined in."""
    user_id = _get_user_id(request)
    modules = module_service.list_modules(user_id, enabled_only=enabled_only)
    result = []
    for module in modules:
        data = module.to_dict()
        active = None
        if module.active_version_id:
            active = module_service.get_version(user_id, module.active_version_id)
        data["active_version"] = active.to_dict() if active else None
        result.append(data)
    return result


@router.get("/versions")
async def list_versions(
    request: Request,
    module_id: Optional[str] = Query(None),
    slug: Optional[str] = Query(None),
):
    user_id = _get_user_id(request)
    module = _resolve_module(user_id, module_id, slug)
    versions = module_service.list_versions(user_id, module.module_id)
    return [v.to_dict() for v in versions]


@router.post("/publish")
async def publish(
    request: Request,
    file: UploadFile,
    module_id: str = Form(...),
    sha256: str = Form(...),
    label: Optional[str] = Form(None),
    icon: Optional[str] = Form(None),
    min_host_version: int = Form(1),
    min_backend_version: Optional[int] = Form(None),
    source_digest: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    activate: bool = Form(True),
):
    user_id = _get_user_id(request)
    # Ownership check must precede the bundle write: storage_key is built from
    # the client-supplied module_id.
    module = module_service.get_module(user_id, module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    # D13 / phase 1.3: a reserved slug can only collide with the management
    # routes once the dispatcher is mounted, but a row can predate that
    # (migrated, or created before reservation), so publish must also refuse
    # it, not just create.
    if module.slug in RESERVED_SLUGS:
        raise HTTPException(status_code=400, detail="slug is reserved")
    if isinstance(description, str) and len(description) > 200:
        raise HTTPException(status_code=400, detail="description must be at most 200 characters")
    content = await file.read()
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != sha256.strip().lower():
        raise HTTPException(status_code=400, detail="sha256 mismatch")
    storage_key = f"module/{module_id}/{actual_sha256}.js"
    _write_bundle(storage_key, content)
    version = module_service.publish(
        user_id,
        module_id,
        ui_sha256=actual_sha256,
        ui_storage_key=storage_key,
        label=label,
        icon=icon,
        min_host_version=min_host_version,
        min_backend_version=min_backend_version,
        source_digest=source_digest,
        description=description,
        activate=activate,
    )
    if not version:
        # Defence in depth; the ownership check above already covers this.
        raise HTTPException(status_code=404, detail="Module not found")
    return version.to_dict()


@router.post("/rollback")
async def rollback(req: RollbackRequest, request: Request):
    user_id = _get_user_id(request)
    module = _resolve_module(user_id, req.module_id, req.slug)
    try:
        updated = module_service.rollback(user_id, module.module_id, from_version_id=req.from_version_id)
    except module_service.RollbackConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"reason": "stale_version", "active_version_id": exc.active_version_id},
        ) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Nothing to roll back to")
    return updated.to_dict()


@router.post("/activate")
async def activate(req: ActivateRequest, request: Request):
    user_id = _get_user_id(request)
    module = _resolve_module(user_id, req.module_id, req.slug)
    updated = module_service.activate(user_id, module.module_id, req.version_no)
    if not updated:
        raise HTTPException(status_code=404, detail="Version not found")
    return updated.to_dict()


@router.post("/enable")
async def set_enabled(req: EnableRequest, request: Request):
    user_id = _get_user_id(request)
    module = _resolve_module(user_id, req.module_id, req.slug)
    updated = module_service.set_enabled(user_id, module.module_id, req.enabled)
    if not updated:
        raise HTTPException(status_code=404, detail="Module not found")
    return updated.to_dict()


@router.post("/delete")
async def delete_module(req: DeleteRequest, request: Request):
    """Hard-delete a module and all of its versions.

    DB rows go first (storage.service.module.delete_module deletes
    version rows, then the module row) so a failure partway through bundle
    cleanup never leaves a row pointing at bytes that are already gone.
    Orphaned bundle bytes after a successful row delete are acceptable and
    are cleaned up best-effort below.
    """
    user_id = _get_user_id(request)
    module = _resolve_module(user_id, req.module_id, req.slug)
    storage_keys = module_service.delete_module(user_id, module.module_id)
    if storage_keys is None:
        # Defence in depth; the resolve above already covers this.
        raise HTTPException(status_code=404, detail="Module not found")
    for key in storage_keys:
        _delete_bundle(key)
    return {
        "module_id": module.module_id,
        "slug": module.slug,
        "deleted_versions": len(storage_keys),
    }


@router.get("/bundle/{version_id}")
async def get_bundle(version_id: str, request: Request):
    user_id = _get_user_id(request)
    version = module_service.get_version(user_id, version_id)
    if not version or not version.ui_storage_key:
        raise HTTPException(status_code=404, detail="Version not found")
    content = _read_bundle(version.ui_storage_key)
    # Bundles are content-addressed and versions immutable, so cache forever.
    return Response(
        content=content,
        media_type="text/javascript",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
