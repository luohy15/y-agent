import click

from yagent.api_client import api_request


@click.command("dismiss")
@click.argument("correction_id")
def english_dismiss(correction_id):
    """Mark a correction as dismissed (excluded from pattern counts)."""
    resp = api_request("POST", "/api/english/dismiss", json={"correction_id": correction_id})
    r = resp.json()
    click.echo(f"Dismissed {r['correction_id']}")
