import click

from yagent.api_client import api_request


@click.command('list')
def trace_share_list():
    """List all trace shares owned by the current user."""
    resp = api_request("GET", "/api/trace/shares")
    shares = resp.json()
    if not shares:
        click.echo("No shares")
        return
    for s in shares:
        pw = " [password]" if s.get("has_password") else ""
        click.echo(f"{s['share_id']}  trace={s['trace_id']}{pw}")
