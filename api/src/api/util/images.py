import base64
import binascii
import errno
import os
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import HTTPException
from loguru import logger

from agent.ec2_wake import ensure_and_touch_vm
from agent.ssh_pool import SSHPool

IMAGE_ASSETS_DIR = Path(os.environ.get("Y_AGENT_IMAGE_DIR", "/Users/roy/luohy15/assets/images"))
_ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
_REMOTE_IMAGE_SCHEMES = {"http", "https"}
_SSH_POOL = SSHPool()


def is_remote_image_reference(image_path: str) -> bool:
    return urlparse(image_path).scheme.lower() in _REMOTE_IMAGE_SCHEMES


class ImageUploadLike(Protocol):
    filename: str
    content_base64: str


def resolve_send_image_path(image_path: str, *, require_exists: bool = True) -> Path | str:
    if not image_path or not image_path.strip():
        raise HTTPException(status_code=400, detail="image path cannot be empty")
    if is_remote_image_reference(image_path):
        return image_path
    path = Path(image_path).expanduser().resolve()
    assets_dir = IMAGE_ASSETS_DIR.expanduser().resolve()
    if path.suffix.lower() not in _ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported image extension")
    if path != assets_dir and assets_dir not in path.parents:
        raise HTTPException(status_code=400, detail="image path must be under assets image dir")
    if require_exists and (not path.exists() or not path.is_file()):
        raise HTTPException(status_code=400, detail="image path does not exist")
    return path


def save_send_image_upload(upload: ImageUploadLike, *, prefix: str = "upload", vm_config=None) -> str:
    filename = Path(upload.filename or "").name
    if not filename:
        raise HTTPException(status_code=400, detail="image filename is required")
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported image extension")
    try:
        data = base64.b64decode(upload.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="invalid image_uploads content_base64")
    if len(data) > _MAX_IMAGE_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="image upload exceeds 10 MB")

    safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "-", Path(filename).stem).strip("-") or "image"
    return save_image_bytes(data, prefix=f"{prefix}-{safe_stem}", suffix=suffix, vm_config=vm_config)


def _image_name(prefix: str, suffix: str) -> str:
    safe_prefix = re.sub(r"[^a-zA-Z0-9_-]", "-", prefix).strip("-") or "image"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%f")[:-3] + "Z"
    return f"{safe_prefix}-{timestamp}-{uuid4().hex[:8]}{suffix}"


def ssh_put_image_bytes(content: bytes, *, prefix: str, suffix: str, vm_config) -> str:
    suffix = suffix.lower()
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    if suffix not in _ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported image extension")
    if vm_config is None or not getattr(vm_config, "vm_name", None) or not getattr(vm_config, "api_token", None):
        raise HTTPException(status_code=503, detail="vm_config with SSH credentials is required to store image bytes")

    image_name = _image_name(prefix, suffix)
    assets_dir = IMAGE_ASSETS_DIR.expanduser().resolve()
    image_path = assets_dir / image_name
    sftp = None

    try:
        ensure_and_touch_vm(vm_config)
        client = _SSH_POOL.get_or_create(vm_config)
        client.exec_command(f"mkdir -p {shlex.quote(str(assets_dir))}")
        sftp = client.open_sftp()
        with sftp.open(str(image_path), "wb") as remote_file:
            remote_file.write(content)
        return str(image_path)
    except Exception as exc:
        logger.exception("ssh image upload failed: {}", exc)
        raise HTTPException(status_code=503, detail="failed to store image on EC2; retry after VM is reachable") from exc
    finally:
        if sftp is not None:
            try:
                sftp.close()
            except Exception:
                pass


def save_image_bytes(content: bytes, *, prefix: str, suffix: str, vm_config=None) -> str:
    suffix = suffix.lower()
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    if suffix not in _ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported image extension")

    image_name = _image_name(prefix, suffix)
    assets_dir = IMAGE_ASSETS_DIR.expanduser().resolve()
    try:
        assets_dir.mkdir(parents=True, exist_ok=True)
        image_path = assets_dir / image_name
        image_path.write_bytes(content)
        return str(image_path)
    except OSError as exc:
        if exc.errno not in (errno.EROFS, errno.EACCES, errno.EPERM):
            raise

    return ssh_put_image_bytes(content, prefix=prefix, suffix=suffix, vm_config=vm_config)


def resolve_message_image_paths(images: list[str] | None, image_uploads: list[ImageUploadLike] | None, *, prefix: str = "upload", vm_config=None) -> list[str] | None:
    safe_paths = [str(resolve_send_image_path(image_path, require_exists=False)) for image_path in (images or [])]
    safe_paths.extend(str(save_send_image_upload(upload, prefix=prefix, vm_config=vm_config)) for upload in (image_uploads or []))
    return safe_paths or None
