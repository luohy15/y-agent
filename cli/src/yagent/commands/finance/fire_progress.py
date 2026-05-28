import click

from storage.service import finance_derived as derived_service

from ._helpers import derived_result_envelope, echo_json, resolve_user_id


@click.command("fire-progress")
@click.option("--user-id", type=int, default=None, help="Numeric user.id to read FIRE progress for")
@click.option("--vm-name", default="", help="VM config name; defaults to empty string")
def fire_progress(user_id: int | None, vm_name: str):
    """Read DB-backed FIRE progress as JSON."""
    result = derived_service.fire_progress(resolve_user_id(user_id), vm_name or "")
    echo_json(derived_result_envelope(result))
