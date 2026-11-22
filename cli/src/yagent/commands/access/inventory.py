import click
from tabulate import tabulate

from yagent.api_client import api_request


@click.command(name="inventory")
def access_inventory():
    """List existing users with maintainer and admission state. Read-only."""
    rows = api_request("GET", "/api/access/inventory").json()
    if not rows:
        click.echo("No users.")
        return
    table = [
        [
            row.get("user_id"),
            row.get("email") or "-",
            row.get("created_at") or "-",
            "yes" if row.get("maintainer") else "no",
            row.get("admission_status") or "-",
        ]
        for row in rows
    ]
    click.echo(tabulate(
        table,
        headers=["User", "Email", "Created", "Maintainer", "Admission"],
        tablefmt="simple",
    ))
