import click

from yagent.api_client import api_request


@click.command(name="approve")
@click.argument("email")
def access_approve(email):
    """Approve a pending application by verified email."""
    row = api_request("POST", "/api/access/applications/approve", json={"email": email}).json()
    click.echo(f"{row.get('email')} {row.get('status')}")
