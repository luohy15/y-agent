import click

from yagent.api_client import api_request


@click.command("add")
@click.argument("url")
@click.option("--title", "-t", default=None, help="Feed title")
def rss_add(url, title):
    """Add a new RSS feed."""
    payload = {"url": url}
    if title:
        payload["title"] = title
    resp = api_request("POST", "/api/rss-feed", json=payload)
    feed = resp.json()
    label = feed.get("title") or feed["url"]
    click.echo(f"Created feed '{label}' ({feed['rss_feed_id']})")
