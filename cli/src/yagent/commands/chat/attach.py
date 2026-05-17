import os
from pathlib import Path

import click
import httpx

from yagent.api_client import api_request
from yagent.util.images import image_upload_payload, is_remote_image_reference


def _attach_image_payload(images: tuple[str, ...]) -> dict:
    remote_images: list[str] = []
    image_uploads: list[dict] = []
    for image in images:
        if is_remote_image_reference(image):
            remote_images.append(image)
            continue

        source = Path(image).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"image not found: {image}")
        image_uploads.append(image_upload_payload(str(source)))

    payload: dict = {}
    if remote_images:
        payload["images"] = remote_images
    if image_uploads:
        payload["image_uploads"] = image_uploads
    return payload


@click.command("attach")
@click.option("--image", "images", multiple=True, required=True, type=str, help="Image path or URL to attach. Repeat for multiple images.")
@click.option("--chat-id", "chat_id", default=None, help="Chat ID to attach to (defaults to Y_CHAT_ID).")
def attach_images(images: tuple[str, ...], chat_id: str | None):
    """Attach images to the latest assistant message in a chat."""
    chat_id = chat_id or os.environ.get("Y_CHAT_ID")
    if not chat_id:
        click.echo("Error: --chat-id is required when Y_CHAT_ID is not set.", err=True)
        raise SystemExit(2)

    try:
        image_payload = _attach_image_payload(images)
        resp = api_request(
            "POST",
            "/api/chat/attach-image",
            json={"chat_id": chat_id, **image_payload},
        )
        data = resp.json()
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            detail = e.response.text
        click.echo(f"Error: {detail}", err=True)
        raise SystemExit(1)

    click.echo(f"attached {data.get('count', len(images))} image(s) to chat {chat_id}")
