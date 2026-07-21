import click
from datetime import datetime
from yagent.api_client import api_request
from yagent.time_filter import collect_time_params, time_filter_options


@click.command('list')
@click.option('--query', '-q', default=None, help='Search by subject, from, or content')
@click.option('--account', '-a', default=None, help='Filter by connected account address')
@click.option('--tag', default=None, help='Filter by tag')
@time_filter_options
@click.option('--limit', '-l', default=50, help='Max emails to return')
@click.option('--offset', '-o', default=0, help='Offset for pagination')
def email_list(query, account, tag, on, from_, to, created_on, created_from, created_to,
               updated_on, updated_from, updated_to, limit, offset):
    """List emails. Canonical time field: date (received)."""
    params = {"limit": limit, "offset": offset}
    if query is not None:
        params["query"] = query
    if account is not None:
        params["account"] = account
    if tag is not None:
        params["tag"] = tag
    params.update(collect_time_params(
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    ))

    resp = api_request("GET", "/api/email/list", params=params)
    emails = resp.json()
    if not emails:
        click.echo("No emails found")
        return

    for e in emails:
        date = datetime.fromtimestamp(e["date"] / 1000).strftime("%Y-%m-%d %H:%M")
        subject = e.get("subject") or "-"
        from_addr = e.get("from_addr", "-")
        thread_id = e.get("thread_id") or "-"
        click.echo(f"[{date}] [{e['email_id']}] [thread:{thread_id}] {from_addr} | {subject}")
