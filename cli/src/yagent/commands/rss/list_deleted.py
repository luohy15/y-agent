import click
from tabulate import tabulate

from yagent.api_client import api_request


@click.command("list-deleted")
@click.option("--limit", type=int, default=50, help="Max rows to return.")
def rss_list_deleted(limit):
    """List soft-deleted RSS feeds."""
    resp = api_request("GET", "/api/rss-feed/deleted", params={"limit": limit})
    feeds = resp.json()
    if not feeds:
        click.echo("No soft-deleted RSS feeds.")
        return

    table = []
    for f in feeds:
        table.append([
            f["rss_feed_id"],
            f.get("title") or "-",
            f["url"],
            f.get("deleted_at") or "-",
        ])
    click.echo(tabulate(table, headers=["ID", "Title", "URL", "Deleted At"], tablefmt="simple"))
