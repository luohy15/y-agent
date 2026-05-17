import os

import click
import httpx

from yagent.api_client import api_request
from yagent.util.images import stage_image_path


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
        staged_images = [stage_image_path(image) for image in images]
        resp = api_request(
            "POST",
            "/api/chat/attach-image",
            json={"chat_id": chat_id, "images": staged_images},
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

    click.echo(f"attached {data.get('count', len(staged_images))} image(s) to chat {chat_id}")
