import glob as _glob
import os
from pathlib import Path

import click

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp'}


def _expand(patterns):
    """Expand each pattern as a glob if it contains wildcards, otherwise use as-is.

    Directories are walked one level deep for supported image extensions.
    """
    paths = []
    for pat in patterns:
        if any(c in pat for c in '*?['):
            matched = sorted(_glob.glob(pat))
            if not matched:
                raise click.ClickException(f"No files match pattern: {pat}")
            paths.extend(Path(m) for m in matched)
            continue
        p = Path(pat)
        if p.is_dir():
            paths.extend(sorted(
                f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXTS
            ))
        else:
            paths.append(p)
    return paths


@click.command('tinify')
@click.argument('inputs', nargs=-1, required=True)
@click.option('--output', '-o', default=None, type=click.Path(),
              help='Output path. Only valid for a single input; defaults to in-place overwrite.')
def image_tinify(inputs, output):
    """Compress images using TinyPNG / Tinify (PNG, JPEG, WebP).

    Accepts one or more files, directories, or glob patterns. Defaults to
    overwriting each input in place. Use -o to write to a specific path
    when compressing a single file.

    Requires TINIFY_API_KEY environment variable. Get a key from
    https://tinypng.com/developers.
    """
    api_key = os.getenv("TINIFY_API_KEY")
    if not api_key:
        raise click.ClickException(
            "TINIFY_API_KEY not found. Set it in your environment or a .env file.\n"
            "Get a key from: https://tinypng.com/developers"
        )

    paths = _expand(inputs)
    if not paths:
        raise click.ClickException("No input files resolved.")

    missing = [p for p in paths if not p.exists()]
    if missing:
        raise click.ClickException(f"File(s) not found: {', '.join(str(p) for p in missing)}")

    if output is not None and len(paths) != 1:
        raise click.ClickException("--output/-o is only allowed with a single input file.")

    import tinify
    tinify.key = api_key

    total_in = 0
    total_out = 0
    for src in paths:
        dst = Path(output) if output else src
        size_in = src.stat().st_size
        try:
            source = tinify.from_file(str(src))
            source.to_file(str(dst))
        except tinify.Error as e:
            raise click.ClickException(f"Tinify failed for {src}: {e}")

        size_out = dst.stat().st_size
        total_in += size_in
        total_out += size_out
        pct = (1 - size_out / size_in) * 100 if size_in else 0
        click.echo(f"  {src} -> {dst}: {size_in:,} -> {size_out:,} bytes ({pct:.1f}% smaller)")

    if len(paths) > 1 and total_in:
        pct = (1 - total_out / total_in) * 100
        click.secho(
            f"Total: {total_in:,} -> {total_out:,} bytes ({pct:.1f}% smaller across {len(paths)} files)",
            fg="green",
        )
