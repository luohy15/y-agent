import base64
from pathlib import Path


def image_upload_payload(image_path: str) -> dict:
    source = Path(image_path).expanduser().resolve()
    return {
        "filename": source.name,
        "content_base64": base64.b64encode(source.read_bytes()).decode("ascii"),
    }
