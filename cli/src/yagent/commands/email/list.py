import click
from datetime import datetime
from yagent.api_client import api_request


@click.command('list')
@click.option('--query', '-q', default=None, help='Search by subject, from, or content')
@click.option('--limit', '-l', default=50, help='Max emails to return')
@click.option('--offset', '-o', default=0, help='Offset for pagination')
def email_list(query, limit, offset):
    """List emails."""
    params = {"limit": limit, "offset": offset}
    if query is not None:
        params["query"] = query

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
