import json

import click
from yagent.api_client import api_request
from .sla_text import sla_label


@click.command('audit')
@click.option('--notify', is_flag=True, help='Send the overdue/due-today digest to Telegram; silent when empty')
@click.option('--json', 'as_json', is_flag=True, help='Print the audit payload as JSON')
def todo_audit(notify, as_json):
    """Read open load, breaches, oldest items and long-term goals."""
    if notify:
        result = api_request("POST", "/api/todo/audit/notify").json()
        click.echo("Digest sent" if result['sent'] else "No digest sent")
        return
    audit = api_request("GET", "/api/todo/audit").json()
    if as_json:
        click.echo(json.dumps(audit, ensure_ascii=False, indent=2))
        return
    click.echo(f"Open: {audit['total']} | Overdue: {audit['overdue_count']} | Today: {audit['today']}")
    for key in ('status_counts', 'priority_counts'):
        click.echo(', '.join(f"{k}: {v}" for k, v in audit[key].items()))
    for key, label in (('overdue', 'Overdue: renew or archive'), ('due_today', 'Due today'),
                       ('oldest', 'Oldest non-pinned'), ('pinned', 'Long-term')):
        click.echo(f"\n{label} ({len(audit[key])})")
        for todo in audit[key]:
            click.echo(f"  {todo['todo_id']} {todo['name']} | {todo['status']} | {sla_label(todo)}")
