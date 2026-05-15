import base64
import binascii
import errno
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from fastapi import HTTPException

IMAGE_ASSETS_DIR = Path(os.environ.get("Y_AGENT_IMAGE_DIR", "/Users/roy/luohy15/assets/images"))
_ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024


class ImageUploadLike(Protocol):
    filename: str
    content_base64: str


def resolve_send_image_path(image_path: str) -> Path:
    if not image_path or not image_path.strip():
        raise HTTPException(status_code=400, detail="image path cannot be empty")
    path = Path(image_path).expanduser().resolve()
    assets_dir = IMAGE_ASSETS_DIR.expanduser().resolve()
    if path.suffix.lower() not in _ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported image extension")
    if path != assets_dir and assets_dir not in path.parents:
        raise HTTPException(status_code=400, detail="image path must be under assets image dir")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=400, detail="image path does not exist")
    return path


def save_send_image_upload(upload: ImageUploadLike, *, prefix: str = "upload") -> Path:
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

    assets_dir = IMAGE_ASSETS_DIR.expanduser().resolve()
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "-", Path(filename).stem).strip("-") or "image"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%f")[:-3] + "Z"
    image_name = f"{prefix}-{timestamp}-{safe_stem}-{uuid4().hex[:8]}{suffix}"
    try:
        assets_dir.mkdir(parents=True, exist_ok=True)
        image_path = assets_dir / image_name
        image_path.write_bytes(data)
        return image_path
    except OSError as exc:
        if exc.errno not in (errno.EROFS, errno.EACCES, errno.EPERM):
            raise
        tmp_dir = Path("/tmp/y-agent-images").resolve()
        tmp_dir.mkdir(parents=True, exist_ok=True)
        image_path = tmp_dir / image_name
        image_path.write_bytes(data)
        return image_path


def resolve_message_image_paths(images: list[str] | None, image_uploads: list[ImageUploadLike] | None, *, prefix: str = "upload") -> list[str] | None:
    safe_paths = [str(resolve_send_image_path(image_path)) for image_path in (images or [])]
    safe_paths.extend(str(save_send_image_upload(upload, prefix=prefix)) for upload in (image_uploads or []))
    return safe_paths or None
