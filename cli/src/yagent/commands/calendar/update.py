import click
from yagent.api_client import api_request
from yagent.time_util import local_to_utc


@click.command('update')
@click.argument('event_id')
@click.option('--summary', '-s', default=None, help='New summary')
@click.option('--start', default=None, help='New start time (local)')
@click.option('--end', default=None, help='New end time (local)')
@click.option('--desc', default=None, help='New description')
@click.option('--todo-id', default=None, type=str, help='Link to todo ID')
def calendar_update(event_id, summary, start, end, desc, todo_id):
    """Update a calendar event."""
    body = {"event_id": event_id}
    if summary is not None:
        body["summary"] = summary
    if start is not None:
        body["start_time"] = local_to_utc(start)
    if end is not None:
        body["end_time"] = local_to_utc(end)
    if desc is not None:
        body["description"] = desc
    if todo_id is not None:
        body["todo_id"] = todo_id

    if len(body) == 1:
        click.echo("No fields to update")
        return

    resp = api_request("POST", "/api/calendar/update", json=body)
    event = resp.json()
    click.echo(f"Updated event '{event['summary']}' ({event['event_id']})")
