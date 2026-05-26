import time
from datetime import datetime, timezone

import click
from tabulate import tabulate

from yagent.api_client import api_request


def _format_expiry(value: int | None) -> str:
    if not value:
        return "-"
    label = datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d")
    if value < int(time.time()) + 7 * 24 * 3600:
        return f"STALE {label}"
    return label


@click.command(name="list")
def cookies_list():
    """List synced cookie domains without showing cookie blobs."""
    resp = api_request("GET", "/api/cookies")
    rows = resp.json()
    if not rows:
        click.echo("No synced cookies.")
        return
    table = [
        [row.get("domain"), row.get("count", 0), _format_expiry(row.get("expires_at")), row.get("updated_at") or "-"]
        for row in rows
    ]
    click.echo(tabulate(table, headers=["Domain", "Count", "Expires", "Updated"], tablefmt="simple"))
