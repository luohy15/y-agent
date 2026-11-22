import click

from yagent.commands.access.client import access_request


@click.command(name="approve")
@click.argument("email")
def access_approve(email):
    """Approve a pending application by verified email."""
    row = access_request("POST", "/api/access/applications/approve", json={"email": email}).json()
    click.echo(f"{row.get('email')} {row.get('status')}")
