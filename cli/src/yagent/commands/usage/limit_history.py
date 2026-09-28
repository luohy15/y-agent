"""`y usage limit-history` (todo 3717): the bounded subscription limit-window
history read. Same window as GET /api/usage/limit-history. The table marks
hours that have no evidence and shows each entry's state and the freshness
of its source at collection time.
"""

from __future__ import annotations

import json
from datetime import timedelta

import click

from storage.service import model_usage_limit_history as history_service
from storage.service.time_range import parse_time_range
from storage.service.user import get_cli_user_id
from storage.util import local_today


def _window(time_expr: str | None, from_date: str | None, to_date: str | None) -> tuple[str, str]:
    if time_expr:
        start, end = parse_time_range(time_expr)
        if start is None or end is None:
            raise click.ClickException("limit history requires a bounded date range")
        return start.isoformat(), (end - timedelta(days=1)).isoformat()
    today = local_today().isoformat()
    return from_date or today, to_date or today


def _print_table(payload: dict) -> None:
    click.echo(
        f"{payload['from_date']} .. {payload['to_date']}  {payload['timezone']}  "
        f"complete={str(payload['complete']).lower()}"
    )
    for hour in payload["hours"]:
        label = f"{hour['date']} {hour['hour']:02d}:00"
        if hour["attempts"] == 0:
            click.echo(f"{label}  no evidence")
            continue
        errors = ",".join(hour["failed_errors"]) if hour["failed_errors"] else "-"
        click.echo(
            f"{label}  attempts={hour['attempts']} ok={hour['ok']} failed={hour['failed']} errors={errors}"
        )
        for entry in hour["entries"]:
            used = entry["used_percent"]
            used_str = f"{used:.0f}%" if isinstance(used, (int, float)) else "-"
            click.echo(
                f"    {entry['backend']:<12} {entry['window_key'] or '-':<16} {used_str:>6}  "
                f"{entry['state']:<16} {entry['freshness']:<12} {entry['reset_at'] or '-'}"
            )


@click.command("limit-history")
@click.option("--time", "time_expr", default=None, help="Shared time grammar (today, ytd, a range)")
@click.option("--from", "from_date", default=None, help="Inclusive start date, YYYY-MM-DD")
@click.option("--to", "to_date", default=None, help="Inclusive end date, YYYY-MM-DD")
@click.option("--backend", default=None, help="Only this backend (claude_code, codex, grok)")
@click.option("--json", "as_json", is_flag=True, help="Print the raw response instead of a table")
def limit_history(time_expr, from_date, to_date, backend, as_json):
    """Show recorded subscription limit-window history, one row per local hour."""
    start, end = _window(time_expr, from_date, to_date)
    try:
        payload = history_service.list_limit_history(get_cli_user_id(), start, end, backend=backend)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(payload, default=str))
        return
    _print_table(payload)
