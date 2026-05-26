import click

from yagent.api_client import api_request


@click.command("update")
@click.argument("rss_feed_id")
@click.option("--title", "-t", default=None, help="New feed title")
@click.option(
    "--type", "-T", "feed_type",
    type=click.Choice(["rss", "scrape"]),
    default=None,
    help="Switch feed type. When switching to 'scrape', supply --item-selector.",
)
@click.option("--item-selector", default=None, help="(scrape) CSS selector matching each item")
@click.option("--title-selector", default=None, help="(scrape) CSS selector for item title within item")
@click.option("--link-selector", default=None, help="(scrape) CSS selector for item link within item")
@click.option("--link-attr", default=None, help="(scrape) attribute holding the link URL (default: href)")
@click.option("--date-selector", default=None, help="(scrape) CSS selector for item date within item")
@click.option("--date-attr", default=None, help="(scrape) attribute holding the date value")
@click.option("--date-format", default=None, help="(scrape) strptime format for the date string")
def rss_update(rss_feed_id, title, feed_type, item_selector, title_selector, link_selector,
               link_attr, date_selector, date_attr, date_format):
    """Update an existing RSS feed (title, type, scrape selectors)."""
    payload = {"rss_feed_id": rss_feed_id}
    if title is not None:
        payload["title"] = title
    if feed_type is not None:
        payload["feed_type"] = feed_type

    scrape_opts = [
        ("item_selector", item_selector),
        ("title_selector", title_selector),
        ("link_selector", link_selector),
        ("link_attr", link_attr),
        ("date_selector", date_selector),
        ("date_attr", date_attr),
        ("date_format", date_format),
    ]
    cfg = {k: v for k, v in scrape_opts if v}
    if cfg:
        if feed_type == "rss":
            raise click.UsageError("scrape selector options cannot be combined with --type rss")
        payload["scrape_config"] = cfg
    elif feed_type == "scrape":
        raise click.UsageError(
            "switching to --type scrape requires at least --item-selector"
        )

    if len(payload) == 1:
        raise click.UsageError("nothing to update; pass --title, --type, or scrape selectors")

    resp = api_request("POST", "/api/rss-feed/update", json=payload)
    feed = resp.json()
    label = feed.get("title") or feed["url"]
    click.echo(f"Updated feed '{label}' ({feed['rss_feed_id']}, type={feed.get('feed_type') or 'rss'})")
