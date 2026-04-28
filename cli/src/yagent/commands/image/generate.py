import os
import shutil
from datetime import datetime
from pathlib import Path

import click
from dotenv import load_dotenv


def _assets_dir() -> Path:
    image_home = os.getenv("IMAGE_HOME")
    if image_home:
        return Path(image_home).expanduser()
    return Path.home() / ".y-image"


@click.command('generate')
@click.option('--prompt', '-p', required=True, help='Prompt for image generation or editing instructions (required).')
@click.option('--input', '-i', 'inputs', multiple=True, help='Input image path. Repeat to combine multiple images.')
@click.option('--output', '-o', default='generated_image.png', show_default=True, help='Output path for generated/edited image.')
def image_generate(prompt, inputs, output):
    """Generate, edit, or combine images using Google Gemini AI.

    Examples:

        y image generate -p "A surreal landscape with floating islands"
        y image generate -p "Add vintage film effect" -i photo.jpg
        y image generate -p "Merge into a collage" -i img1.jpg -i img2.jpg
        y image generate -p "A serene sunset" -o sunset.png
    """
    load_dotenv()

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise click.ClickException(
            "GOOGLE_API_KEY not found. Set it in your environment or a .env file.\n"
            "Get a key from: https://aistudio.google.com/apikey"
        )

    from google import genai
    from PIL import Image

    client = genai.Client(api_key=api_key)

    if inputs:
        contents = []
        for img_path in inputs:
            img_file = Path(img_path)
            if not img_file.exists():
                raise click.ClickException(f"Input image not found: {img_path}")
            contents.append(Image.open(img_file))
        contents.append(prompt)

        if len(inputs) == 1:
            click.echo(f"Editing image: {inputs[0]}")
        else:
            click.echo(f"Combining {len(inputs)} images:")
            for img_path in inputs:
                click.echo(f"  - {img_path}")
        click.echo(f"Prompt: {prompt}")
    else:
        click.echo(f"Generating image with prompt: {prompt}")
        contents = [prompt]

    response = client.models.generate_content(
        model="gemini-3-pro-image-preview",
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

            assets_dir = _assets_dir()
            assets_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            assets_path = assets_dir / f"generated_{timestamp}{output_file.suffix}"
            shutil.copy2(output_file, assets_path)
            click.secho(f"✓ Copy saved to assets: {assets_path}", fg="cyan")
            return

    click.echo("No image was generated.")
