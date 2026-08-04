"""`y module schema-sql <slug>` — print DDL for a module's entities (plan 4.2).

Imports the module's local `entities` submodule (if any) and renders its
metadata's CREATE TABLE / CREATE INDEX statements under the PostgreSQL
dialect to stdout. This only *renders* text — `CreateTable(...).compile()`
needs no engine or connection, so the command works with DATABASE_URL unset.
It never executes anything; comparing this output against the live schema
(or diffing it to write a migration) is left to the maintainer.
"""

from __future__ import annotations

import click
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from ._local import import_local_entities
from ._paths import validate_slug


@click.command("schema-sql")
@click.argument("slug")
def module_schema_sql(slug):
    """Print CREATE TABLE/INDEX DDL for <slug>'s entities.

    Prints nothing and exits 0 for a module with no `entities` submodule
    (it owns no tables).
    """
    try:
        slug = validate_slug(slug)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        entities_mod = import_local_entities(slug)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise click.ClickException(f"failed to import {slug}.entities: {exc}") from exc

    if entities_mod is None:
        return

    metadata = getattr(entities_mod, "metadata", None)
    if metadata is None:
        raise click.ClickException(f"{slug}.entities does not export `metadata`")

    from agent.module_host import owned_tables

    dialect = postgresql.dialect()
    statements = []
    # Reference stubs for host kernel tables (D4) are skipped: they exist in the
    # metadata only so the module's foreign keys resolve.
    for table in owned_tables(metadata):
        statements.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in table.indexes:
            statements.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")

    if statements:
        click.echo("\n\n".join(statements))
