import click

from yagent.api_client import api_request


@click.command("list")
@click.option("--type", "-t", default=None, help="Filter by type")
@click.option("--limit", "-l", default=50, help="Max results")
@click.option("--offset", "-o", default=0, help="Offset")
def entity_list(type, limit, offset):
    """List entities."""
    params = {"limit": limit, "offset": offset}
    if type:
        params["type"] = type
    resp = api_request("GET", "/api/entity/list", params=params)
    entities = resp.json()
    if not entities:
        click.echo("No entities.")
        return
    for e in entities:
        click.echo(f"  {e['entity_id']} [{e['type']}]: {e['name']}")
