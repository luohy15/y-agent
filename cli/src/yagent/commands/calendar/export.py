import click
from storage.service.user import get_cli_user_id
from .dashboard import update_dashboard


@click.command('export')
def calendar_export():
    """Export calendar events to markdown dashboard."""
    user_id = get_cli_user_id()
    path = update_dashboard(user_id)
    click.echo(f"Exported calendar to {path}")
