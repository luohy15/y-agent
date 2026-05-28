import click

from storage.service import finance_derived as derived_service

from ._helpers import derived_result_envelope, echo_json, resolve_user_id


@click.command("balance-sheet")
@click.option("--user-id", type=int, default=None, help="Numeric user.id to read finance data for")
@click.option("--vm-name", default="", help="VM config name; defaults to empty string")
@click.option("--time", default="", help="Time filter (e.g. month, ytd, 2024, day-30 to day-1)")
@click.option("--history", is_flag=True, help="Output time-series metrics instead of detail")
@click.option("--granularity", type=click.Choice(["weekly", "monthly", "quarterly", "yearly"]), default="monthly")
@click.option("--convert", default="USD", help="Convert all amounts to this currency")
@click.option("--breakdown", type=click.Choice(["positions"]), default=None, help="Return position-level asset breakdown")
@click.option("--risky-only", is_flag=True, help="Only include risky holdings for position breakdown")
def balance_sheet(user_id: int | None, vm_name: str, time: str, history: bool, granularity: str, convert: str, breakdown: str | None, risky_only: bool):
    """Read DB-backed balance-sheet data as JSON."""
    target_user_id = resolve_user_id(user_id)
    if breakdown == "positions":
        result = derived_service.balance_sheet_positions(target_user_id, vm_name or "", time, granularity, convert or None, risky_only=risky_only)
    else:
        result = derived_service.balance_sheet(target_user_id, vm_name or "", time, history, granularity, convert or None)
    echo_json(derived_result_envelope(result))
