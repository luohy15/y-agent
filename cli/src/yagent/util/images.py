import base64
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4


IMAGE_ASSETS_DIR = Path("/Users/roy/luohy15/assets/images")
_ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_REMOTE_IMAGE_SCHEMES = {"http", "https", "s3"}


def is_remote_image_reference(image_path: str) -> bool:
    return urlparse(image_path).scheme.lower() in _REMOTE_IMAGE_SCHEMES


def image_upload_payload(image_path: str) -> dict:
    source = Path(image_path).expanduser().resolve()
    return {
        "filename": source.name,
        "content_base64": base64.b64encode(source.read_bytes()).decode("ascii"),
    }


def _asset_name(source: Path) -> str:
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "-", source.stem).strip("-") or "image"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%f")[:-3] + "Z"
    return f"cli-{timestamp}-{safe_stem}-{uuid4().hex[:8]}{source.suffix.lower()}"


def stage_image_path(image_path: str) -> str:
    if is_remote_image_reference(image_path):
        return image_path

    source = Path(image_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"image not found: {image_path}")
    if source.suffix.lower() not in _ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("unsupported image extension")

    assets_dir = IMAGE_ASSETS_DIR.expanduser().resolve()
    if source == assets_dir or assets_dir in source.parents:
        return str(source)

    assets_dir.mkdir(parents=True, exist_ok=True)
    staged_path = assets_dir / _asset_name(source)
    shutil.copy2(source, staged_path)
    return str(staged_path)
