import click

from yagent.api_client import api_request


@click.command("list")
def tag_list():
    """List distinct tags for the user, with usage counts."""
    resp = api_request("GET", "/api/tag/list")
    tags = resp.json()
    if not tags:
        click.echo("No tags.")
        return
    for t in tags:
        click.echo(f"  {t['tag']} ({t['count']})")
