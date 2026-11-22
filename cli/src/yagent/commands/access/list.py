import click
from tabulate import tabulate

from yagent.api_client import api_request


@click.command(name="list")
@click.option("--status", type=click.Choice(["pending", "approved"]), help="Filter by admission status.")
def access_list(status):
    """List access applications."""
    params = {"status": status} if status else None
    rows = api_request("GET", "/api/access/applications", params=params).json()
    if not rows:
        click.echo("No applications.")
        return
    table = [
        [
            row.get("email"),
            row.get("status"),
            row.get("source"),
            row.get("request_count"),
            row.get("notification_status"),
            row.get("notification_attempts"),
            row.get("decided_by") or "-",
        ]
        for row in rows
    ]
    click.echo(tabulate(
        table,
        headers=["Email", "Status", "Source", "Requests", "Notice", "Attempts", "Decided by"],
        tablefmt="simple",
    ))
