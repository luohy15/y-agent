import click
from datetime import datetime
from yagent.api_client import api_request


def _print_email(e):
    date = datetime.fromtimestamp(e["date"] / 1000).strftime("%Y-%m-%d %H:%M")
    click.echo(f"ID: {e['email_id']}")
    click.echo(f"Subject: {e.get('subject') or '-'}")
    click.echo(f"From: {e.get('from_addr', '-')}")
    click.echo(f"To: {', '.join(e.get('to_addrs') or [])}")
    if e.get('cc_addrs'):
        click.echo(f"Cc: {', '.join(e['cc_addrs'])}")
    click.echo(f"Date: {date}")
    if e.get('thread_id'):
        click.echo(f"Thread: {e['thread_id']}")
    click.echo("---")
    click.echo(e.get('content') or '')


@click.command('get')
@click.argument('id')
@click.option('--thread', '-t', is_flag=True, help='Get all emails in a thread by thread_id')
def email_get(id, thread):
    """Get an email by email_id, or all emails in a thread with --thread."""
    if thread:
        resp = api_request("GET", f"/api/email/thread/{id}")
        emails = resp.json()
        if not emails:
            click.echo("No emails found in thread")
            return
        for i, e in enumerate(emails):
            if i > 0:
                click.echo("\n===\n")
            _print_email(e)
    else:
        resp = api_request("GET", f"/api/email/{id}")
        _print_email(resp.json())
