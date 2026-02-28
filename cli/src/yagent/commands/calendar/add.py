import click
from yagent.api_client import api_request
from yagent.time_util import local_to_utc


@click.command('add')
@click.option('--summary', '-s', required=True, help='Event summary')
@click.option('--start', required=True, help='Start time (local, e.g. 2026-02-16T10:00)')
@click.option('--end', default=None, help='End time (local)')
@click.option('--desc', default=None, help='Description')
@click.option('--todo-id', default=None, type=str, help='Link to todo ID')
@click.option('--all-day', is_flag=True, default=False, help='All-day event')
@click.option('--source', default=None, help='Event source')
def calendar_add(summary, start, end, desc, todo_id, all_day, source):
    """Add a new calendar event."""
    body = {"summary": summary, "start": local_to_utc(start)}
    if end is not None:
        body["end"] = local_to_utc(end)
    if desc is not None:
        body["description"] = desc
    if todo_id is not None:
        body["todo_id"] = todo_id
    if all_day:
        body["all_day"] = True
    if source is not None:
        body["source"] = source

    resp = api_request("POST", "/api/calendar", json=body)
    event = resp.json()
    click.echo(f"Created event '{event['summary']}' ({event['event_id']})")
