import click

from yagent.api_client import api_request


@click.command("remove")
@click.argument("rss_feed_id")
def rss_remove(rss_feed_id):
    """Remove an RSS feed."""
    api_request("POST", "/api/rss-feed/delete", json={"rss_feed_id": rss_feed_id})
    click.echo(f"Deleted feed {rss_feed_id}")
