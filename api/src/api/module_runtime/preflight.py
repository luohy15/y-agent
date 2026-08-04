"""Publish-time schema preflight (plan D7).

`y module publish` must refuse a module whose declared entities reference
schema the database lacks, without ever running DDL itself: migrations are
always hand-applied (AGENTS.md). This module only *inspects*
`information_schema` via `sqlalchemy.inspect(engine)` and reports every
missing table/column in one message, never the first alone. It checks
presence only, never type, nullability, or index shape: extra columns in the
database are the benign rollback direction.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.engine import Engine
from sqlalchemy.inspection import inspect as sa_inspect

from agent.module_host import owned_tables


class SchemaPreflightError(Exception):
    """A module's declared entities reference schema the database lacks.

    `report` names every missing table/column so the publish response can
    surface the whole diff, not just the first miss.
    """

    def __init__(self, slug: str, report: str):
        self.slug = slug
        self.report = report
        super().__init__(report)


def check_metadata_against_database(slug: str, metadata: MetaData, engine: Engine) -> None:
    """Raise SchemaPreflightError naming every missing table/column, else return None."""
    insp = sa_inspect(engine)
    missing_tables: list[str] = []
    missing_columns: dict[str, set[str]] = {}

    # Reference stubs for host kernel tables (D4) are declared only so the
    # module's foreign keys resolve; the module does not own their schema.
    for table in owned_tables(metadata):
        table_name = ".".join(part for part in (table.schema, table.name) if part)
        if not insp.has_table(table.name, schema=table.schema):
            missing_tables.append(table_name)
            continue
        existing = {c["name"] for c in insp.get_columns(table.name, schema=table.schema)}
        declared = {c.name for c in table.columns}
        missing = declared - existing
        if missing:
            missing_columns[table_name] = missing

    if not missing_tables and not missing_columns:
        return

    lines = [f"schema preflight failed for module {slug!r}:"]
    for name in missing_tables:
        lines.append(f"  missing table: {name}")
    for name, cols in missing_columns.items():
        lines.append(f"  table {name!r} missing columns: {', '.join(sorted(cols))}")
    raise SchemaPreflightError(slug, "\n".join(lines))
