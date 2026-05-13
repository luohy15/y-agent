import click
from tabulate import tabulate

from yagent.api_client import api_request
from yagent.time_filter import collect_time_params, time_filter_options


@click.command("list")
@time_filter_options
def rss_list(on, from_, to, created_on, created_from, created_to,
             updated_on, updated_from, updated_to):
    """List RSS feeds. Canonical time field: last_fetched_at."""
    params = collect_time_params(
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    )
    resp = api_request("GET", "/api/rss-feed/list", params=params or None)
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
