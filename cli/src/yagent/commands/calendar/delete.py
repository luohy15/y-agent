import click
from storage.service import calendar_event as cal_service
from storage.service.user import get_cli_user_id
from .dashboard import update_dashboard


@click.command('delete')
@click.argument('event_id')
def calendar_delete(event_id):
    """Soft delete a calendar event."""
    user_id = get_cli_user_id()
    event = cal_service.delete_event(user_id, event_id)
    if not event:
        click.echo(f"Event '{event_id}' not found")
        return
    click.echo(f"Deleted event '{event.summary}' ({event.event_id})")
    update_dashboard(user_id)
