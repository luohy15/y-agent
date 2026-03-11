import click
import numpy as np
from pathlib import Path
from PIL import Image

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff'}


def collect_images(paths):
    """Collect image file paths from files and directories, sorted by name."""
    result = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            result.extend(sorted(
                f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXTS
            ))
        else:
            result.append(p)
    return result


def to_gray(img):
    """Convert PIL Image to grayscale float32 numpy array."""
    return np.array(img.convert('L')).astype(np.float32)


def find_common_header(imgs):
    """Find how many rows from the top are identical across all images."""
    arrays = [to_gray(img) for img in imgs]
    min_h = min(a.shape[0] for a in arrays)
    limit = min_h // 3

    common = 0
    for y in range(limit):
        ref = arrays[0][y]
        if all(np.mean(np.abs(a[y] - ref)) < 3 for a in arrays[1:]):
            common = y + 1
        else:
            break
    return common


def find_common_footer(imgs):
    """Find how many rows from the bottom are identical across all images."""
    arrays = [to_gray(img) for img in imgs]
    min_h = min(a.shape[0] for a in arrays)
    limit = min_h // 3

    common = 0
    for offset in range(limit):
        ref = arrays[0][-(offset + 1)]
        if all(np.mean(np.abs(a[-(offset + 1)] - ref)) < 3 for a in arrays[1:]):
            common = offset + 1
        else:
            break
    return common


def find_overlap(top_img, bot_img, min_h=20):
    """Find vertical pixel overlap between bottom of top_img and top of bot_img.

    Compares grayscale values in the center chat area only (excluding left/right
    edges where background patterns may differ). Uses multi-block consensus voting.
    """
    top_gray = to_gray(top_img)
    bot_gray = to_gray(bot_img)

    h_top, w = top_gray.shape
    h_bot = bot_gray.shape[0]

    # Only compare the center 60% of width (the chat content area)
    x1 = w * 2 // 10
    x2 = w * 8 // 10
    top_crop = top_gray[:, x1:x2]
    bot_crop = bot_gray[:, x1:x2]

    block_h = min(50, h_top // 8)
    search_limit = min(h_bot // 2, h_bot - block_h)
    if search_limit <= 0:
        return 0

    # Try multiple blocks from the bottom portion of the top image
    votes = {}
    start_y = max(h_top // 2, h_top - 400)
    step = max(block_h // 2, 20)

    for by in range(start_y, h_top - block_h - 10, step):
        block = top_crop[by:by + block_h]

        # Skip low-variance (blank) blocks
        if np.var(block) < 50:
            continue

        best_err = float('inf')
        best_y = 0
        for y in range(0, search_limit):
            err = np.mean(np.abs(bot_crop[y:y + block_h] - block))
            if err < best_err:
                best_err = err
                best_y = y

        if best_err < 15:
            overlap = (h_top - by) + best_y
            # Round to nearest 5px to group close votes
            bucket = round(overlap / 5) * 5
            votes[bucket] = votes.get(bucket, 0) + 1

    if not votes:
        return 0

    # Find the overlap value with the most votes
    best_bucket = max(votes, key=votes.get)
    if votes[best_bucket] < 2:
        return 0

    overlap = best_bucket
    if overlap < min_h or overlap > min(h_top, h_bot):
        return 0

    return overlap


@click.command('splice')
@click.argument('images', nargs=-1, required=True, type=click.Path(exists=True))
@click.option('--output', '-o', default=None, help='Output file path. Defaults to spliced.png in current directory.')
@click.option('--crop-top', type=int, default=None, help='Pixels to crop from top of each image (auto-detected if omitted).')
@click.option('--crop-bottom', type=int, default=None, help='Pixels to crop from bottom of each image (auto-detected if omitted).')
def image_splice(images, output, crop_top, crop_bottom):
    """Splice multiple images vertically into one continuous image.

    Accepts image files or directories. Automatically detects and removes
    common header/footer areas (e.g., app chrome) and pixel overlaps to
    produce a seamless result.
    """
    paths = collect_images(images)
    if len(paths) < 2:
        raise click.ClickException("Need at least 2 images to splice.")

    imgs = [Image.open(p).convert('RGB') for p in paths]

    # Use the width of the first image as reference
    target_width = imgs[0].width
    resized = []
    for img in imgs:
        if img.width != target_width:
            ratio = target_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((target_width, new_height), Image.LANCZOS)
        resized.append(img)

    # Auto-detect common header/footer if not specified
    header = crop_top if crop_top is not None else find_common_header(resized)
    footer = crop_bottom if crop_bottom is not None else find_common_footer(resized)

    if header > 0 or footer > 0:
        click.echo(f"  Cropping: {header}px top, {footer}px bottom")

    # Crop header/footer from interior images
    cropped = []
    for i, img in enumerate(resized):
        top = header if i > 0 else 0
        bottom = img.height - footer if i < len(resized) - 1 else img.height
        cropped.append(img.crop((0, top, img.width, bottom)))

    # Detect pixel overlaps between cropped images
    overlaps = []
    for i in range(len(cropped) - 1):
        overlap = find_overlap(cropped[i], cropped[i + 1])
        overlaps.append(overlap)
        if overlap > 0:
            click.echo(f"  {paths[i].name} <-> {paths[i+1].name}: {overlap}px overlap")

    # Stitch
    total_height = cropped[0].height
    for i in range(1, len(cropped)):
        total_height += cropped[i].height - overlaps[i - 1]

    result = Image.new('RGB', (target_width, total_height))
    y = 0
    result.paste(cropped[0], (0, 0))
    y += cropped[0].height
    for i in range(1, len(cropped)):
        y -= overlaps[i - 1]
        result.paste(cropped[i], (0, y))
        y += cropped[i].height

    if output is None:
        output = "spliced.png"

    result.save(output)
    click.echo(f"Saved to {output} ({target_width}x{total_height})")
