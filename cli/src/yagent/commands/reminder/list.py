import click
from tabulate import tabulate
from yagent.api_client import api_request
from yagent.time_filter import collect_time_params, time_filter_options
from yagent.time_util import utc_to_local


@click.command('list')
@click.option('--status', '-s', default=None, help='Filter by status (pending/sent/cancelled)')
@click.option('--tag', default=None, help='Filter reminders by entity_tag (exact tag match)')
@time_filter_options
@click.option('--limit', '-l', default=50, help='Max results')
def reminder_list(status, tag, on, from_, to, created_on, created_from, created_to,
                  updated_on, updated_from, updated_to, limit):
    """List reminders. Canonical time field: remind_at."""
    params = {"limit": limit}
    if status is not None:
        params["status"] = status
    if tag:
        params["tag"] = tag
    params.update(collect_time_params(
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    ))

    resp = api_request("GET", "/api/reminder/list", params=params)
    reminders = resp.json()
    if not reminders:
        click.echo("No reminders found")
        return

    table = []
    for r in reminders:
        assoc = r.get("todo_id") or r.get("calendar_event_id") or "-"
        table.append([
            r["reminder_id"],
            r["title"],
            utc_to_local(r["remind_at"]),
            r["status"],
            assoc,
        ])
    click.echo(tabulate(table, headers=["ID", "Title", "Remind At", "Status", "Assoc"], tablefmt="simple"))
