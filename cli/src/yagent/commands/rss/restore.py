import click

from yagent.api_client import api_request


@click.command("restore")
@click.argument("rss_feed_id")
def rss_restore(rss_feed_id):
    """Restore a soft-deleted RSS feed."""
    api_request("POST", "/api/rss-feed/restore", json={"rss_feed_id": rss_feed_id})
    click.echo(f"Restored feed {rss_feed_id}")
