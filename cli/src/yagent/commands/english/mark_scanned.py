import click

from yagent.api_client import api_request


@click.command("mark-scanned")
@click.argument("scanned_through_unix", type=int)
def english_mark_scanned(scanned_through_unix):
    """Advance the scan watermark to the given unix ms (batch max)."""
    resp = api_request(
        "POST",
        "/api/english/mark-scanned",
        json={"scanned_through_unix": scanned_through_unix},
    )
    r = resp.json()
    click.echo(f"Watermark advanced to {r.get('scanned_through_unix')}")
