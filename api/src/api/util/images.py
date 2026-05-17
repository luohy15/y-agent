import base64
import binascii
import errno
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import HTTPException

IMAGE_ASSETS_DIR = Path(os.environ.get("Y_AGENT_IMAGE_DIR", "/Users/roy/luohy15/assets/images"))
_ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
_REMOTE_IMAGE_SCHEMES = {"http", "https", "s3"}


def is_remote_image_reference(image_path: str) -> bool:
    return urlparse(image_path).scheme.lower() in _REMOTE_IMAGE_SCHEMES


def _s3_bucket() -> str:
    return os.environ.get("Y_AGENT_S3_BUCKET", "")


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


def save_send_image_upload(upload: ImageUploadLike, *, prefix: str = "upload") -> str:
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
    return save_image_bytes(data, prefix=f"{prefix}-{safe_stem}", suffix=suffix)


def save_image_bytes(content: bytes, *, prefix: str, suffix: str) -> str:
    suffix = suffix.lower()
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    if suffix not in _ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="unsupported image extension")

    safe_prefix = re.sub(r"[^a-zA-Z0-9_-]", "-", prefix).strip("-") or "image"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%f")[:-3] + "Z"
    image_name = f"{safe_prefix}-{timestamp}-{uuid4().hex[:8]}{suffix}"
    assets_dir = IMAGE_ASSETS_DIR.expanduser().resolve()
    try:
        assets_dir.mkdir(parents=True, exist_ok=True)
        image_path = assets_dir / image_name
        image_path.write_bytes(content)
        return str(image_path)
    except OSError as exc:
        if exc.errno not in (errno.EROFS, errno.EACCES, errno.EPERM):
            raise

    bucket = _s3_bucket()
    if not bucket:
        raise RuntimeError("Y_AGENT_S3_BUCKET is required when image assets dir is not writable")

    key = f"images/{image_name}"
    import boto3

    boto3.client("s3").put_object(
        Bucket=bucket,
        Key=key,
        Body=content,
        ContentType=f"image/{'jpeg' if suffix in {'.jpg', '.jpeg'} else suffix.lstrip('.')}",
    )
    return f"s3://{bucket}/{key}"


def resolve_message_image_paths(images: list[str] | None, image_uploads: list[ImageUploadLike] | None, *, prefix: str = "upload") -> list[str] | None:
    safe_paths = [str(resolve_send_image_path(image_path, require_exists=False)) for image_path in (images or [])]
    safe_paths.extend(str(save_send_image_upload(upload, prefix=prefix)) for upload in (image_uploads or []))
    return safe_paths or None
