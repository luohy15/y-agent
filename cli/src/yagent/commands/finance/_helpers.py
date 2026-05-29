import json

import click

from storage.service.user import get_cli_user_id


def resolve_user_id(user_id: int | None) -> int:
    return user_id or get_cli_user_id()


def echo_json(payload: dict):
    click.echo(json.dumps(payload))


def json_option(f):
    """Add a --json flag that emits the raw JSON envelope instead of a table."""
    return click.option("--json", "as_json", is_flag=True, help="Output the raw JSON envelope instead of a table")(f)


def derived_envelope(data, synced_at: str | None, source: str = "derived") -> dict:
    return {"data": data, "synced_at": synced_at or "", "source": source}


def derived_result_envelope(result, source: str = "derived") -> dict:
    return {"data": result.data, **result.meta, "synced_at": result.synced_at or "", "source": source}


def rows_envelope(rows, source: str = "db") -> dict:
    synced_at = rows[0].synced_at if rows else ""
    return {"data": [row.to_dict() for row in rows], "synced_at": synced_at, "source": source}
