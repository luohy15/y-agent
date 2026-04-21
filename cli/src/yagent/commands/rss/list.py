import click
from tabulate import tabulate

from yagent.api_client import api_request


@click.command("list")
def rss_list():
    """List RSS feeds."""
    resp = api_request("GET", "/api/rss-feed/list")
    feeds = resp.json()
    if not feeds:
        click.echo("No RSS feeds.")
        return

    table = []
    for f in feeds:
        table.append([
            f["rss_feed_id"],
            f.get("title") or "-",
            f["url"],
            f.get("feed_type") or "rss",
            f.get("last_fetched_at") or "-",
        ])
    click.echo(tabulate(table, headers=["ID", "Title", "URL", "Type", "Last Fetched"], tablefmt="simple"))
