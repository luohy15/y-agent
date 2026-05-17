import base64
from pathlib import Path

import click
from yagent.api_client import api_request


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
