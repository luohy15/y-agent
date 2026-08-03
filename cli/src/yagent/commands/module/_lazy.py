"""Lazy root-CLI registration for module-owned Click groups (plan phase 5).

`list_commands` only scans `$Y_AGENT_HOME/modules` (listdir + `module.json`);
no module Python is imported. `get_command` returns a placeholder that imports
`<pkg>.cli` only when that group is actually resolved. Built-in commands win
on name collision so a local module cannot shadow `todo` / `module` / etc.
"""

from __future__ import annotations

import json
from typing import Optional

import click

from ._local import import_local_cli
from ._paths import SLUG_RE, meta_path, modules_dir, source_dir


def discover_module_slugs() -> list[str]:
    """Return discoverable module slugs under the canonical modules directory.

    Skips dot-entries (`.sdk`, `.sdk-node_modules.bak`), non-directories,
    invalid slug names, directories without `module.json`, and UI-only modules
    that have no `cli.py` yet. Does not import any module Python.
    """
    root = modules_dir()
    if not root.is_dir():
        return []
    slugs: list[str] = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    for entry in entries:
        name = entry.name
        if name.startswith("."):
            continue
        if not entry.is_dir():
            continue
        if not SLUG_RE.match(name):
            continue
        if not (entry / "module.json").is_file():
            continue
        # CLI half is optional; only advertise modules that actually ship one.
        # Presence is a filesystem check — still no import on the help path.
        if not (entry / "cli.py").is_file():
            continue
        slugs.append(name)
    return sorted(slugs)


def module_short_help(slug: str) -> Optional[str]:
    """Read short help from `module.json` only (no Python import)."""
    path = meta_path(slug)
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    label = meta.get("label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    description = meta.get("description")
    if isinstance(description, str) and description.strip():
        # Keep one line for Click's Commands listing.
        return description.strip().splitlines()[0].strip()
    return None


def is_discoverable_module(slug: str) -> bool:
    if not SLUG_RE.match(slug):
        return False
    root = source_dir(slug)
    return (
        root.is_dir()
        and (root / "module.json").is_file()
        and (root / "cli.py").is_file()
    )


class LazyModuleProxy(click.Group):
    """Placeholder group that imports `<slug>.cli` only when resolved.

    Click's `get_command` returns this lightweight stand-in during help /
    discovery (so no module Python is imported on `y --help`). Once Click
    actually resolves a module command it calls `make_context`, which we
    delegate to the real group; from then on `ctx.command` is the real group
    and its own options, callback, subcommands, and Click error handling
    behave exactly as they do for a built-in. `shell_complete` is the one
    other method Click invokes on the stand-in before resolution, so it too
    is forwarded.
    """

    def __init__(self, slug: str, short_help: Optional[str] = None):
        help_text = short_help or f"Module command group for {slug!r}."
        super().__init__(
            name=slug,
            help=help_text,
            short_help=short_help,
        )
        self.slug = slug
        self._real: Optional[click.Group] = None

    def _load(self) -> click.Group:
        if self._real is not None:
            return self._real

        cli_path = source_dir(self.slug) / "cli.py"
        if not cli_path.is_file():
            raise click.ClickException(
                f"module {self.slug!r} has no CLI (expected {cli_path})"
            )

        try:
            cli_mod = import_local_cli(self.slug)
            group = getattr(cli_mod, "group", None)
            if group is None:
                raise AttributeError(
                    f"module {self.slug!r} cli.py must export `group` "
                    "(a click.Group)"
                )
            if not isinstance(group, click.Group):
                raise TypeError(
                    f"module {self.slug!r} cli.py export `group` must be a "
                    f"click.Group, got {type(group).__name__}"
                )
            self._real = group
            return group
        except click.ClickException:
            raise
        except BaseException as exc:
            # Leave a clear trail without dumping a full traceback into the
            # normal CLI path; Click will print the message.
            raise click.ClickException(
                f"Failed to load CLI for module {self.slug!r}: {exc}"
            ) from exc

    def make_context(
        self,
        info_name,
        args,
        parent=None,
        **extra,
    ):
        return self._load().make_context(info_name, args, parent=parent, **extra)

    def shell_complete(self, ctx: click.Context, incomplete: str):
        return self._load().shell_complete(ctx, incomplete)


class LazyModuleGroup(click.Group):
    """Root `y` group: built-ins plus lazily discovered module groups."""

    def list_commands(self, ctx: click.Context) -> list[str]:
        names = set(super().list_commands(ctx))
        names.update(discover_module_slugs())
        return sorted(names)

    def get_command(self, ctx: click.Context, cmd_name: str) -> Optional[click.Command]:
        # Built-ins always win. A module named `todo` / `module` / `finance`
        # (while finance is still built-in) cannot shadow the host command.
        builtin = super().get_command(ctx, cmd_name)
        if builtin is not None:
            return builtin
        if not is_discoverable_module(cmd_name):
            return None
        return LazyModuleProxy(cmd_name, short_help=module_short_help(cmd_name))
