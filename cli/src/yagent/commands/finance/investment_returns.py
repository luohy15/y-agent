import click

from storage.service import finance_derived as derived_service

from ._helpers import derived_result_envelope, echo_json, json_option, resolve_user_id
from ._render import render_investment_returns


@click.command("investment-returns")
@click.option("--user-id", type=int, default=None, help="Numeric user.id to read finance data for")
@click.option("--vm-name", default="", help="VM config name; defaults to empty string")
@click.option("--time", default="ytd", help="Time filter (e.g. ytd, mtd, 2024, day-30 to day-1)")
@click.option("--history", is_flag=True, help="Output the cumulative return time-series instead of a summary")
@click.option("--granularity", type=click.Choice(["weekly", "monthly", "quarterly", "yearly"]), default="monthly")
@click.option("--convert", default="USD", help="Convert all amounts to this currency")
@json_option
def investment_returns(user_id: int | None, vm_name: str, time: str, history: bool, granularity: str, convert: str, as_json: bool):
    """Read DB-backed investment-returns data (table by default; --json for the raw envelope).

    Realized return is the net of the configurable investment-income subtree
    (default Income:Investment); unrealized is current market value minus book
    value; total return combines the two. --history shows the cumulative
    total-return curve per period.
    """
    result = derived_service.investment_returns(resolve_user_id(user_id), vm_name or "", time, history, granularity, convert or None)
    envelope = derived_result_envelope(result)
    if as_json:
        echo_json(envelope)
    else:
        render_investment_returns(envelope, history)
