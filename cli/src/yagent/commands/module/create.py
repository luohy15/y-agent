"""`y module create <slug>` — scaffold source + materialize SDK (decision D5/D7)."""

from __future__ import annotations

import json
import shutil
import sys

import click
import httpx

from ._api import create_module, resolve_module
from ._paths import (
    entities_dir,
    meta_path,
    migration_dir,
    repository_dir,
    source_dir,
    source_path,
    ui_dir,
    validate_slug,
)
from ._sdk import ensure_sdk, load_contract, package_sdk_root


ICON_KEYS = load_contract()["icons"]

# D11: the module's own DeclarativeBase + a local copy of the host's
# four-column timestamp mixin. storage.util is on the D9 pure-function
# allowlist (no DB, no entity) so reusing its timestamp helpers here does not
# couple the module to any host repository/service/entity.
_ENTITIES_BASE_PY = '''"""<slug>'s own DeclarativeBase and timestamp mixin (plan D11).

Deliberately NOT importing storage.entity.base.Base: declarative copies mixin
Columns per class, so that would technically work, but it couples the module
to a host symbol for nothing. This local copy makes the ownership claim
literal.
"""

from sqlalchemy import BigInteger, Column, String
from sqlalchemy.orm import DeclarativeBase
from storage.util import get_unix_timestamp, get_utc_iso8601_timestamp


class Base(DeclarativeBase):
    pass


class BaseEntity:
    created_at = Column(String, default=get_utc_iso8601_timestamp)
    updated_at = Column(String, default=get_utc_iso8601_timestamp, onupdate=get_utc_iso8601_timestamp)
    created_at_unix = Column(BigInteger, default=get_unix_timestamp)
    updated_at_unix = Column(BigInteger, default=get_unix_timestamp, onupdate=get_unix_timestamp)
'''

_ENTITIES_INIT_PY = '''"""Exports `metadata` (and `Base`) by fixed convention (plan D11).

Both the publish preflight and `y module schema-sql` look for
`<pkg>.entities.metadata` and treat its absence as "this module owns no
tables" (UI-only modules, backend modules with no storage). Import every
entity module below so its table registers on `metadata` before either
consumer inspects it, e.g.:

    from . import widget  # noqa: F401
"""

from .base import Base  # noqa: F401

metadata = Base.metadata
'''

_REPOSITORY_README = """Module-owned repositories over module-owned tables (plan D11).

Each repository opens its own session via `agent.module_host.session()` (the
host contract's re-export of `storage.database.base.get_db()`), the same
commit-on-clean-exit shape host repositories use. No host repository or
service is imported from here.
"""

_MIGRATION_README = """Hand-applied SQL only (plan D11 / AGENTS.md).

Nothing in this repo executes files under this directory: `y module publish`
excludes it from the build, and the API never reads it. One file per schema
change, run manually via `psql` by the maintainer. Keep changes expand-only
(add table/column; never drop or rename in the same step a live version
might still read) so a rollback to a previous published version keeps
working against the same database.

`y module schema-sql <slug>` prints the current CREATE TABLE/INDEX DDL for
this module's entities, for comparison against what the live database
already has — it never executes anything either.
"""


@click.command("create")
@click.argument("slug")
@click.option("--label", default=None, help="Sidebar label (default: title-cased slug)")
@click.option(
    "--icon",
    default="box",
    show_default=True,
    help=f"Sidebar icon key ({', '.join(ICON_KEYS)})",
)
@click.option("--force", is_flag=True, help="Overwrite existing source/meta files")
@click.option(
    "--no-register",
    is_flag=True,
    help="Scaffold locally only; skip POST /api/module/create",
)
def module_create(slug, label, icon, force, no_register):
    """Scaffold a starter module under $Y_AGENT_HOME/modules/ and bootstrap the SDK."""
    try:
        slug = validate_slug(slug)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        ensure_sdk()
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    src = source_path(slug)
    meta = meta_path(slug)
    if (src.exists() or meta.exists()) and not force:
        raise click.ClickException(
            f"module {slug!r} already exists ({source_dir(slug)}); use --force to overwrite"
        )

    templates = package_sdk_root() / "templates"
    root = source_dir(slug)
    root.mkdir(parents=True, exist_ok=True)
    ui_dir(slug).mkdir(parents=True, exist_ok=True)
    shutil.copy2(templates / "starter.tsx", src)

    # D11: __init__.py must stay empty so the API half never transitively
    # imports the CLI half (or beancount). Scaffold it empty; do not add
    # imports here later.
    init_py = root / "__init__.py"
    if not init_py.exists() or force:
        init_py.write_text(
            "# Module package root. KEEP EMPTY — API and CLI halves must load independently.\n",
            encoding="utf-8",
        )

    # Phase 4 (D11): the data half. entities/ carries the module's own
    # DeclarativeBase; repository/ and migration/ are scaffolded with READMEs
    # only (no entity/table is invented here — that's the author's next step).
    entities = entities_dir(slug)
    entities.mkdir(parents=True, exist_ok=True)
    entities_init = entities / "__init__.py"
    if not entities_init.exists() or force:
        entities_init.write_text(_ENTITIES_INIT_PY, encoding="utf-8")
    entities_base = entities / "base.py"
    if not entities_base.exists() or force:
        entities_base.write_text(_ENTITIES_BASE_PY.replace("<slug>", slug), encoding="utf-8")

    repository = repository_dir(slug)
    repository.mkdir(parents=True, exist_ok=True)
    repo_readme = repository / "README.md"
    if not repo_readme.exists() or force:
        repo_readme.write_text(_REPOSITORY_README, encoding="utf-8")

    migration = migration_dir(slug)
    migration.mkdir(parents=True, exist_ok=True)
    migration_readme = migration / "README.md"
    if not migration_readme.exists() or force:
        migration_readme.write_text(_MIGRATION_README, encoding="utf-8")

    meta_body = {
        "label": label or slug.replace("-", " ").replace("_", " ").title(),
        "icon": icon,
        "description": "",
        "parts": ["ui"],
        "min_backend_version": None,
    }
    meta.write_text(json.dumps(meta_body, indent=2) + "\n", encoding="utf-8")

    module_id = None
    if not no_register:
        try:
            existing = resolve_module(slug)
            if existing:
                module_id = existing["module_id"]
                click.echo(f"Already registered: {slug} ({module_id})")
            else:
                created = create_module(slug)
                module_id = created["module_id"]
                click.echo(f"Registered: {slug} ({module_id})")
        except httpx.HTTPStatusError as exc:
            # S3 may not have shipped POST /api/module/create yet; local scaffold still succeeds.
            detail = _http_detail(exc)
            click.echo(
                f"Warning: could not register with API ({exc.response.status_code}: {detail}). "
                "Local files were written; publish will retry registration.",
                err=True,
            )
        except (httpx.HTTPError, SystemExit) as exc:
            # Not logged in / network: still leave the scaffold.
            click.echo(
                f"Warning: could not register with API ({exc}). Local files were written.",
                err=True,
            )

    click.echo(f"Created {src}")
    click.echo(f"         {meta}")
    click.echo(f"Edit the source, then: y module publish {slug}")


def _http_detail(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
        if isinstance(body, dict) and "detail" in body:
            return str(body["detail"])
    except Exception:
        pass
    return (exc.response.text or "")[:200]
