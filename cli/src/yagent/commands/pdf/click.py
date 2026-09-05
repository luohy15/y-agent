from typing import Optional

import click

from .parse import pdf_parse
from ..module._lazy import LazyModuleProxy, is_discoverable_module


def _load_export_pdf_command() -> click.Command:
    """Resolve the file module's `export-pdf` command (todo 3371 T6).

    One implementation lives in `code/y-module/file/cli.py`; this is a thin
    alias so `y pdf export` and `y file export-pdf` run the same code.
    Delegates group loading to `LazyModuleProxy` so a broken `file/cli.py`
    surfaces the same wrapped `ClickException` as `y file ...` instead of a
    raw traceback.
    """
    group = LazyModuleProxy("file")._load()
    command = group.commands.get("export-pdf")
    if command is None:
        raise click.ClickException(
            "module 'file' has no `export-pdf` command (expected `y file export-pdf`)"
        )
    return command


class LazyExportPdfCommand(click.Command):
    """Placeholder for `y pdf export`.

    Mirrors `LazyModuleProxy` (module/_lazy.py): the module import happens
    only in `make_context` / `shell_complete`, so listing `y pdf --help`
    never imports the file module just to read its short help.
    """

    _HELP = "Export a Markdown file to PDF (alias for `y file export-pdf`)."

    def __init__(self):
        super().__init__(name="export", help=self._HELP, short_help=self._HELP)
        self._real: Optional[click.Command] = None

    def _load(self) -> click.Command:
        if self._real is None:
            self._real = _load_export_pdf_command()
        return self._real

    def make_context(self, info_name, args, parent=None, **extra):
        return self._load().make_context(info_name, args, parent=parent, **extra)

    def shell_complete(self, ctx: click.Context, incomplete: str):
        return self._load().shell_complete(ctx, incomplete)


class PdfGroup(click.Group):
    """`y pdf` built-ins plus a lazy `export` alias for `y file export-pdf`."""

    def list_commands(self, ctx: click.Context) -> list[str]:
        names = set(super().list_commands(ctx))
        if is_discoverable_module("file"):
            names.add("export")
        return sorted(names)

    def get_command(self, ctx: click.Context, cmd_name: str):
        builtin = super().get_command(ctx, cmd_name)
        if builtin is not None:
            return builtin
        if cmd_name == "export" and is_discoverable_module("file"):
            return LazyExportPdfCommand()
        return None


@click.group('pdf', cls=PdfGroup)
def pdf_group():
    """PDF tools."""
    pass


pdf_group.add_command(pdf_parse)
