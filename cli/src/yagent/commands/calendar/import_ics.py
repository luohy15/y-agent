import os
import click
from storage.service import calendar_event as cal_service
from storage.service.user import get_cli_user_id
from .dashboard import update_dashboard


@click.command('import')
@click.option('--dir', '-d', 'ics_dir', default=None, help='Directory containing .ics files (default: $Y_AGENT_HOME/assets/calendar/ics)')
def calendar_import(ics_dir):
    """Import events from ICS files."""
    if not ics_dir:
        agent_home = os.path.expanduser(os.getenv("Y_AGENT_HOME", "~/.y-agent"))
        ics_dir = os.path.join(agent_home, "assets", "calendar", "ics")

    if not os.path.isdir(ics_dir):
        click.echo(f"Directory not found: {ics_dir}")
        return

    user_id = get_cli_user_id()
    count = cal_service.import_ics(user_id, ics_dir)
    click.echo(f"Imported {count} events from {ics_dir}")
    update_dashboard(user_id)
