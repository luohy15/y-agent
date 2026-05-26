import click

from yagent.api_client import api_request


@click.command(name="delete")
@click.argument("domain")
def cookies_delete(domain: str):
    """Delete synced cookies for DOMAIN."""
    resp = api_request("DELETE", "/api/cookies", params={"domain": domain})
    deleted = resp.json().get("deleted", False)
    click.echo(f"Deleted cookies for {domain}" if deleted else f"No cookies found for {domain}")
