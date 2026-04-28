from pathlib import Path

import click
import pymupdf
import pymupdf4llm


@click.command('parse')
@click.argument('input_pdf', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--output', '-o', default=None, type=click.Path(path_type=Path),
              help='Output markdown path. Default: assets/pdf/<input_basename>.md (created if needed).')
def pdf_parse(input_pdf: Path, output: Path | None):
    """Parse a PDF into Markdown.

    Examples:

        y pdf parse paper.pdf
        y pdf parse paper.pdf -o /tmp/out.md
    """
    if input_pdf.suffix.lower() != '.pdf':
        raise click.ClickException(f"Not a PDF file: {input_pdf}")

    if output is None:
        output = Path('assets/pdf') / f"{input_pdf.stem}.md"
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        doc = pymupdf.open(str(input_pdf))
    except Exception as e:
        raise click.ClickException(f"Failed to open PDF: {e}")

    try:
        if doc.is_encrypted and not doc.authenticate(""):
            raise click.ClickException(
                f"PDF is password-protected: {input_pdf}. "
                "Decrypt it first (e.g. `qpdf --password=PWD --decrypt in.pdf out.pdf`)."
            )

        try:
            markdown = pymupdf4llm.to_markdown(doc)
        except Exception as e:
            raise click.ClickException(f"Failed to parse PDF: {e}")
    finally:
        doc.close()

    output.write_text(markdown, encoding='utf-8')
    click.secho(f"✓ Markdown saved to: {output}", fg="green")
