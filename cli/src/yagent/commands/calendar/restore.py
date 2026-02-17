import click
from storage.service import calendar_event as cal_service
from storage.service.user import get_cli_user_id


@click.command('restore')
@click.argument('event_id')
def calendar_restore(event_id):
    """Restore a soft-deleted calendar event."""
    user_id = get_cli_user_id()
    event = cal_service.restore_event(user_id, event_id)
    if not event:
        click.echo(f"Event '{event_id}' not found or not deleted")
        return
    click.echo(f"Restored event '{event.summary}' ({event.event_id})")
