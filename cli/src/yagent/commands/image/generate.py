import base64
import os
import shutil
from datetime import datetime
from pathlib import Path

import click

from storage.global_config import load_global_config


GEMINI_MODEL = "gemini-3-pro-image-preview"
OPENAI_MODEL = "gpt-image-2"


def _assets_dir() -> Path:
    image_home = os.getenv("IMAGE_HOME")
    if image_home:
        return Path(image_home).expanduser()
    return Path.home() / ".y-image"


def _archive(output_file: Path) -> None:
    assets_dir = _assets_dir()
    assets_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    assets_path = assets_dir / f"generated_{timestamp}{output_file.suffix}"
    shutil.copy2(output_file, assets_path)
    click.secho(f"✓ Copy saved to assets: {assets_path}", fg="cyan")


def _validate_inputs(inputs):
    for img_path in inputs:
        if not Path(img_path).exists():
            raise click.ClickException(f"Input image not found: {img_path}")


def _echo_action(prompt, inputs):
    if not inputs:
        click.echo(f"Generating image with prompt: {prompt}")
    elif len(inputs) == 1:
        click.echo(f"Editing image: {inputs[0]}")
        click.echo(f"Prompt: {prompt}")
    else:
        click.echo(f"Combining {len(inputs)} images:")
        for img_path in inputs:
            click.echo(f"  - {img_path}")
        click.echo(f"Prompt: {prompt}")


def _generate_gemini(prompt, inputs, output):
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise click.ClickException(
            "GOOGLE_API_KEY not found. Set it in ~/.y-agent/config.toml.\n"
            "Get a key from: https://aistudio.google.com/apikey"
        )

    from google import genai
    from PIL import Image

    client = genai.Client(api_key=api_key)

    if inputs:
        contents = [Image.open(p) for p in inputs]
        contents.append(prompt)
    else:
        contents = [prompt]

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
    )

    for part in response.parts:
        if part.text is not None:
            click.echo(f"Response: {part.text}")
        elif part.inline_data is not None:
            image = part.as_image()
            output_file = Path(output)
            image.save(output_file)
            click.secho(f"✓ Image saved to: {output}", fg="green")
            _archive(output_file)
            return

    click.echo("No image was generated.")


def _generate_openai(prompt, inputs, output):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise click.ClickException(
            "OPENAI_API_KEY not found. Set it in ~/.y-agent/config.toml.\n"
            "Get a key from: https://platform.openai.com/api-keys"
        )

    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    if inputs:
        image_files = [open(p, "rb") for p in inputs]
        try:
            image_arg = image_files[0] if len(image_files) == 1 else image_files
            response = client.images.edit(
                model=OPENAI_MODEL,
                image=image_arg,
                prompt=prompt,
                n=1,
                size="1024x1024",
            )
        finally:
            for f in image_files:
                f.close()
    else:
        response = client.images.generate(
            model=OPENAI_MODEL,
            prompt=prompt,
            n=1,
            size="1024x1024",
        )

    if not response.data:
        click.echo("No image was generated.")
        return

    item = response.data[0]
    b64 = getattr(item, "b64_json", None)
    if b64:
        image_bytes = base64.b64decode(b64)
    else:
        url = getattr(item, "url", None)
        if not url:
            raise click.ClickException("OpenAI response missing both b64_json and url.")
        import httpx
        image_bytes = httpx.get(url, timeout=60).content

    output_file = Path(output)
    output_file.write_bytes(image_bytes)
    click.secho(f"✓ Image saved to: {output}", fg="green")
    _archive(output_file)


@click.command('generate')
@click.option('--prompt', '-p', required=True, help='Prompt for image generation or editing instructions (required).')
@click.option('--input', '-i', 'inputs', multiple=True, help='Input image path. Repeat to combine multiple images.')
@click.option('--output', '-o', default='generated_image.png', show_default=True, help='Output path for generated/edited image.')
@click.option(
    '--provider',
    type=click.Choice(['gemini', 'openai'], case_sensitive=False),
    default=None,
    help='Image provider (default: gemini, override via $IMAGE_PROVIDER).',
)
def image_generate(prompt, inputs, output, provider):
    """Generate, edit, or combine images via Google Gemini or OpenAI gpt-image-2.

    Examples:

        y image generate -p "A surreal landscape with floating islands"
        y image generate -p "Add vintage film effect" -i photo.jpg
        y image generate -p "Merge into a collage" -i img1.jpg -i img2.jpg
        y image generate -p "A red 64px square on white" --provider openai
    """
    load_global_config()

    if provider is None:
        provider = os.getenv("IMAGE_PROVIDER", "gemini").lower()
    else:
        provider = provider.lower()

    if inputs:
        _validate_inputs(inputs)
    _echo_action(prompt, inputs)

    if provider == "gemini":
        _generate_gemini(prompt, inputs, output)
    elif provider == "openai":
        _generate_openai(prompt, inputs, output)
    else:
        raise click.ClickException(f"Unknown provider: {provider}")
