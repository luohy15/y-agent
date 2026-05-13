import click

from yagent.api_client import api_request
from yagent.time_filter import collect_time_params, time_filter_options


@click.command("list")
@click.option("--type", "-t", default=None, help="Filter by type")
@click.option("--limit", "-l", default=50, help="Max results")
@click.option("--offset", "-o", default=0, help="Offset")
@time_filter_options
def entity_list(type, limit, offset,
                on, from_, to, created_on, created_from, created_to,
                updated_on, updated_from, updated_to):
    """List entities. Canonical time field: updated_at."""
    params = {"limit": limit, "offset": offset}
    if type:
        params["type"] = type
    params.update(collect_time_params(
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    ))
    resp = api_request("GET", "/api/entity/list", params=params)
    entities = resp.json()
    if not entities:
        click.echo("No entities.")
        return
    for e in entities:
        click.echo(f"  {e['entity_id']} [{e['type']}]: {e['name']}")
