import click
import httpx
from yagent.api_client import api_request
from yagent.tag_option import resolve_tags


@click.command('add')
@click.argument('name')
@click.option('--desc', '-d', default=None, help='Description')
@click.option('--due', '-u', default=None, help='Due date (YYYY-MM-DD)')
@click.option('--priority', '-p', default=None, type=click.Choice(['low', 'medium', 'high', 'none']), help='Priority')
@click.option('--tags', '-t', 'tags', multiple=True,
              help='Tags: repeat -t and/or comma-separate (e.g. -t cli -t "agent-config,tags")')
@click.option('--sla', default=None, help='Completion promise: Nd, Nw or YYYY-MM-DD (at most 14 days)')
@click.option('--pin', is_flag=True, help='Create a long-term goal without an SLA')
@click.option('--activate', is_flag=True, help='Create the todo already active')
@click.option('--quiet', '-q', is_flag=True, help='Print only the new todo ID (for ID=$(y todo add ...))')
def todo_add(name, desc, due, priority, tags, activate, quiet, sla, pin):
    """Add a new todo."""
    if pin and sla is not None:
        raise click.UsageError("--pin cannot be combined with --sla")
    body = {"name": name, "pinned": pin}
    if sla is not None:
        body["sla"] = sla
    if desc is not None:
        body["desc"] = desc
    if due is not None:
        body["due_date"] = due
    if priority is not None:
        body["priority"] = priority
    resolved_tags = resolve_tags(tags)
    if resolved_tags is not None:
        body["tags"] = resolved_tags

    try:
        resp = api_request("POST", "/api/todo", json=body)
    except httpx.HTTPStatusError as exc:
        raise click.ClickException(str(exc)) from exc
    todo = resp.json()
    if activate:
        try:
            api_request("POST", "/api/todo/status", json={"todo_id": todo['todo_id'], "status": "active"})
        except httpx.HTTPStatusError as exc:
            raise click.ClickException(
                f"Created todo {todo['todo_id']} but failed to activate it: {exc}"
            ) from exc
    if quiet:
        click.echo(todo['todo_id'])
    else:
        click.echo(f"Created todo '{todo['name']}' ({todo['todo_id']}){', active' if activate else ''}")
