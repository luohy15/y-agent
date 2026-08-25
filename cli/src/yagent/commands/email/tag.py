"""Thread-scoped email tag commands."""

import click

from yagent.api_client import api_request


@click.group("tag")
def email_tag_group():
    """Manage tags on an email thread ID."""


@email_tag_group.command("list")
@click.argument("thread_id")
def list_tags(thread_id):
    """List tags for THREAD_ID."""
    response = api_request("GET", f"/api/email/thread/{thread_id}/tags")
    for tag in response.json()["tags"]:
        click.echo(tag)


@email_tag_group.command("add")
@click.argument("thread_id")
@click.argument("tag")
def add_tag(thread_id, tag):
    """Add an existing canonical TAG to THREAD_ID."""
    response = api_request(
        "POST",
        f"/api/email/thread/{thread_id}/tags",
        json={"tag": tag},
    )
    result = response.json()
    click.echo("Added" if result["added"] else "Already present")


@email_tag_group.command("rm")
@click.argument("thread_id")
@click.argument("tag")
def remove_tag(thread_id, tag):
    """Remove TAG from THREAD_ID."""
    response = api_request(
        "POST",
        f"/api/email/thread/{thread_id}/tags/remove",
        json={"tag": tag},
    )
    result = response.json()
    click.echo("Removed" if result["removed"] else "Not present")
