import click

from storage.service import finance_derived as derived_service

from ._helpers import derived_envelope, echo_json, json_option, resolve_user_id
from ._render import render_income_statement


@click.command("income-statement")
@click.option("--user-id", type=int, default=None, help="Numeric user.id to read finance data for")
@click.option("--vm-name", default="", help="VM config name; defaults to empty string")
@click.option("--time", default="month", help="Time filter (e.g. month, ytd, 2024, day-30 to day-1)")
@click.option("--history", is_flag=True, help="Output time-series metrics instead of detail")
@click.option("--granularity", type=click.Choice(["weekly", "monthly", "quarterly", "yearly"]), default="monthly")
@click.option("--convert", default="USD", help="Convert all amounts to this currency")
@click.option("--breakdown", type=click.Choice(["", "categories"]), default="", help="Optional detailed breakdown")
@json_option
def income_statement(user_id: int | None, vm_name: str, time: str, history: bool, granularity: str, convert: str, breakdown: str, as_json: bool):
    """Read DB-backed income-statement data (table by default; --json for the raw envelope).

    Table view shows income as a positive earned amount (matching the web Income
    Statement); --json preserves the raw beancount signs (income negative).
    """
    if breakdown == "categories":
        result = derived_service.income_statement_categories(resolve_user_id(user_id), vm_name or "", time, granularity, convert or None)
    else:
        result = derived_service.income_statement(resolve_user_id(user_id), vm_name or "", time, history, granularity, convert or None)
    envelope = derived_envelope(result.data, result.synced_at)
    if as_json:
        echo_json(envelope)
    else:
        render_income_statement(envelope, history, breakdown)
