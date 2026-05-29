import click

from storage.service import finance_derived as derived_service

from ._helpers import derived_result_envelope, echo_json, json_option, resolve_user_id
from ._render import render_fire_progress


@click.command("fire-progress")
@click.option("--user-id", type=int, default=None, help="Numeric user.id to read FIRE progress for")
@click.option("--vm-name", default="", help="VM config name; defaults to empty string")
@json_option
def fire_progress(user_id: int | None, vm_name: str, as_json: bool):
    """Read DB-backed FIRE progress (table by default; --json for the raw envelope)."""
    result = derived_service.fire_progress(resolve_user_id(user_id), vm_name or "")
    envelope = derived_result_envelope(result)
    if as_json:
        echo_json(envelope)
    else:
        render_fire_progress(envelope)
