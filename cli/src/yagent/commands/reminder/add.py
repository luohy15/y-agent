import click
from yagent.api_client import api_request
from yagent.time_util import utc_to_local


@click.command('add')
@click.argument('title')
@click.option('--at', 'remind_at', required=True, help='Remind time (e.g. 2026-04-18T09:00)')
@click.option('--desc', '-d', default=None, help='Description')
@click.option('--todo', 'todo_id', default=None, help='Associated todo ID')
@click.option('--event', 'calendar_event_id', default=None, help='Associated calendar event ID')
def reminder_add(title, remind_at, desc, todo_id, calendar_event_id):
    """Add a new reminder."""
    body = {"title": title, "remind_at": remind_at}
    if desc is not None:
        body["description"] = desc
    if todo_id is not None:
        body["todo_id"] = todo_id
    if calendar_event_id is not None:
        body["calendar_event_id"] = calendar_event_id

    resp = api_request("POST", "/api/reminder", json=body)
    r = resp.json()
    click.echo(f"Created reminder '{r['title']}' ({r['reminder_id']}) at {utc_to_local(r['remind_at'])}")
