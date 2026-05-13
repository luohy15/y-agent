import click
from datetime import datetime
from yagent.api_client import api_request
from yagent.time_filter import collect_time_params, time_filter_options
from yagent.time_util import _get_configured_tz


@click.command('list')
@click.option('--query', '-q', default=None, help='Search by URL or title')
@time_filter_options
@click.option('--limit', '-l', default=10000, help='Max raw activities from API')
@click.option('--todo', '-t', default=None, help='Filter by todo ID')
@click.option('--show-id', is_flag=True, default=False, help='Show activity_id in output')
def link_list(query, on, from_, to, created_on, created_from, created_to,
              updated_on, updated_from, updated_to, limit, todo, show_id):
    """List browser history links. Canonical time field: visit timestamp."""
    params = {"limit": limit}
    if query is not None:
        params["query"] = query
    if todo is not None:
        params["todo_id"] = todo
    params.update(collect_time_params(
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    ))

    resp = api_request("GET", "/api/link/list", params=params)
    links = resp.json()
    if not links:
        click.echo("No links found")
        return

    for l in links:
        local_tz = _get_configured_tz()
        time = datetime.fromtimestamp(l["timestamp"] / 1000, tz=local_tz).strftime("%H:%M")
        title = l.get("title") or "-"
        if show_id:
            click.echo(f"[{time}] ({l['activity_id']}) {title} {l['base_url']}")
        else:
            click.echo(f"[{time}] {title} {l['base_url']}")
