import click

from yagent.api_client import api_request


@click.command("get")
@click.argument("tag")
@click.option("--prefix", is_flag=True, default=False, help="Prefix match (e.g. 'work/' matches 'work/foo')")
def tag_get(tag, prefix):
    """Find everything tagged TAG, grouped by entity type."""
    resp = api_request("GET", "/api/tag", params={"tag": tag, "prefix": prefix})
    grouped = resp.json()
    if not grouped:
        click.echo(f"Nothing tagged '{tag}'.")
        return
    for entity_type, items in grouped.items():
        click.echo(f"{entity_type}:")
        for item in items:
            if item.get("title"):
                click.echo(f"  - {item['id']}: {item['title']}")
            else:
                click.echo(f"  - {item['id']}")
