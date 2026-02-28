import click
from .dashboard import update_dashboard


@click.command('export')
def calendar_export():
    """Export calendar events to markdown dashboard."""
    path = update_dashboard()
    click.echo(f"Exported calendar to {path}")
