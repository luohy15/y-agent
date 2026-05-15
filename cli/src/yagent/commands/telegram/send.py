import os
import re
import shutil
import base64
from datetime import datetime, timezone
from pathlib import Path

import click
from yagent.api_client import api_request


IMAGE_ASSETS_DIR = Path(os.environ.get("Y_AGENT_IMAGE_DIR", "/Users/roy/luohy15/assets/images"))


def _stage_image_for_telegram(image_path: str) -> str:
    source = Path(image_path).expanduser().resolve()
    assets_dir = IMAGE_ASSETS_DIR.expanduser().resolve()
    if source == assets_dir or assets_dir in source.parents:
        return str(source)

    assets_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%f")[:-3] + "Z"
    stem = re.sub(r"[^a-zA-Z0-9_-]", "-", source.stem).strip("-") or "image"
    dest = assets_dir / f"telegram-send-{timestamp}-{stem}{source.suffix.lower()}"
    shutil.copy2(source, dest)
    return str(dest)


def _image_upload_payload(image_path: str) -> dict:
    source = Path(image_path).expanduser().resolve()
    return {
        "filename": source.name,
        "content_base64": base64.b64encode(source.read_bytes()).decode("ascii"),
    }


@click.command('send')
@click.option('-m', '--message', 'text', default='', help='Message body (markdown ok)')
@click.option('--topic', default=None, help="Forum topic name (omit for DM). 'manager' is an alias for DM.")
@click.option('--image', 'images', multiple=True, type=click.Path(exists=True, dir_okay=False, resolve_path=True), help='Image path to send. Repeat for multiple images.')
def telegram_send(text, topic, images):
    """Send a Telegram message or image to the user's DM or a bound forum topic."""
    if not text and not images:
        raise click.UsageError("Provide --message and/or --image")
    body = {"text": text}
    if topic is not None:
        body["topic"] = topic
    if images:
        body["image_uploads"] = [_image_upload_payload(image) for image in images]
    api_request("POST", "/api/telegram/send", json=body)
    click.echo("sent")
