import click

from yagent.api_client import api_request


@click.command("add")
@click.argument("url")
@click.option("--title", "-t", default=None, help="Feed title")
@click.option(
    "--type", "-T", "feed_type",
    type=click.Choice(["rss", "scrape"]),
    default="rss",
    show_default=True,
    help="Feed type. 'scrape' parses HTML via CSS selectors.",
)
@click.option("--item-selector", default=None, help="(scrape) CSS selector matching each item")
@click.option("--title-selector", default=None, help="(scrape) CSS selector for item title within item")
@click.option("--link-selector", default=None, help="(scrape) CSS selector for item link within item")
@click.option("--link-attr", default=None, help="(scrape) attribute holding the link URL (default: href)")
@click.option("--date-selector", default=None, help="(scrape) CSS selector for item date within item")
@click.option("--date-attr", default=None, help="(scrape) attribute holding the date value")
@click.option("--date-format", default=None, help="(scrape) strptime format for the date string")
def rss_add(url, title, feed_type, item_selector, title_selector, link_selector,
            link_attr, date_selector, date_attr, date_format):
    """Add a new RSS feed. Use --type scrape with --item-selector for HTML scraping."""
    payload = {"url": url, "feed_type": feed_type}
    if title:
        payload["title"] = title

    if feed_type == "scrape":
        if not item_selector:
            raise click.UsageError("--item-selector is required for --type scrape")
        cfg = {"item_selector": item_selector}
        for key, val in [
            ("title_selector", title_selector),
            ("link_selector", link_selector),
            ("link_attr", link_attr),
            ("date_selector", date_selector),
            ("date_attr", date_attr),
            ("date_format", date_format),
        ]:
            if val:
                cfg[key] = val
        payload["scrape_config"] = cfg
    else:
        scrape_opts = {
            "--item-selector": item_selector,
            "--title-selector": title_selector,
            "--link-selector": link_selector,
            "--link-attr": link_attr,
            "--date-selector": date_selector,
            "--date-attr": date_attr,
            "--date-format": date_format,
        }
        used = [flag for flag, val in scrape_opts.items() if val]
        if used:
            raise click.UsageError(
                f"{', '.join(used)} only apply with --type scrape"
            )

    resp = api_request("POST", "/api/rss-feed", json=payload)
    feed = resp.json()
    label = feed.get("title") or feed["url"]
    click.echo(f"Created feed '{label}' ({feed['rss_feed_id']}, type={feed.get('feed_type') or 'rss'})")
