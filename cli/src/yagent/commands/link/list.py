import click
from datetime import datetime, timedelta
from yagent.api_client import api_request
from yagent.time_util import _get_configured_tz


def _parse_time(value):
    """Parse a time string to unix ms. Supports 'today', 'yesterday', 'Nd' (N days ago), or YYYY-MM-DD."""
    local_tz = _get_configured_tz()
    now = datetime.now(tz=local_tz)
    v = value.strip().lower()
    if v == "today":
        return int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    if v == "yesterday":
        d = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        return int(d.timestamp() * 1000)
    if v.endswith("d") and v[:-1].isdigit():
        d = now - timedelta(days=int(v[:-1]))
        return int(d.timestamp() * 1000)
    # YYYY-MM-DD
    dt = datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=local_tz)
    return int(dt.timestamp() * 1000)


@click.command('list')
@click.option('--query', '-q', default=None, help='Search by URL or title')
@click.option('--start', '-s', default=None, help='Start time: today, yesterday, 3d, or YYYY-MM-DD')
@click.option('--end', '-e', default=None, help='End time: today, yesterday, 3d, or YYYY-MM-DD')
@click.option('--limit', '-l', default=10000, help='Max raw activities from API')
def link_list(query, start, end, limit):
    """List browser history links."""
    params = {"limit": limit}
    if query is not None:
        params["query"] = query
    if start is not None:
        params["start"] = _parse_time(start)
    if end is not None:
        params["end"] = _parse_time(end)

    resp = api_request("GET", "/api/link/list", params=params)
    links = resp.json()
    if not links:
        click.echo("No links found")
        return

    for l in links:
        local_tz = _get_configured_tz()
        time = datetime.fromtimestamp(l["timestamp"] / 1000, tz=local_tz).strftime("%H:%M")
        title = l.get("title") or "-"
        click.echo(f"[{time}] {title} {l['base_url']}")
