import os

import click

from yagent.api_client import api_request


def _resolve_activity_id(id_value):
    """If id_value looks like a file path, import it as a page link and return the activity_id.
    Otherwise return id_value as-is."""
    if '/' in id_value or id_value.endswith('.md'):
        if not os.path.isfile(id_value):
            click.echo(f"File not found: {id_value}", err=True)
            raise SystemExit(1)
        title = os.path.basename(id_value).removesuffix('.md')
        with open(id_value, 'r') as f:
            content = f.read()
        resp = api_request("POST", "/api/link/from-page", json={"path": id_value, "title": title, "content": content})
        data = resp.json()
        activity_id = data.get('activity_id')
        click.echo(f"Imported: {id_value} -> {data.get('link_id', '?')}")
        return activity_id
    return id_value


@click.command('assoc')
@click.argument('ids', nargs=-1, required=True)
@click.option('--todo', '-t', required=True, help='Todo ID to associate with')
def link_assoc(ids, todo):
    """Associate links with a todo. Each ID can be an activity_id or a local file path."""
    activity_ids = []
    for id_value in ids:
        try:
            activity_ids.append(_resolve_activity_id(id_value))
        except (SystemExit, Exception) as e:
            click.echo(f"  ! {id_value}: {e}", err=True)

    if not activity_ids:
        return

    resp = api_request("POST", "/api/link-todo/batch", json={"activity_ids": activity_ids, "todo_id": todo})
    data = resp.json()
    click.echo(f"Associated {data.get('created', 0)}/{len(activity_ids)} links with todo {todo}")


@click.command('unassoc')
@click.argument('activity_id')
@click.option('--todo', '-t', required=True, help='Todo ID to disassociate from')
def link_unassoc(activity_id, todo):
    """Remove association between a link activity and a todo."""
    resp = api_request("POST", "/api/link-todo/delete", json={"activity_id": activity_id, "todo_id": todo})
    data = resp.json()
    if data.get("deleted"):
        click.echo(f"Removed association between activity {activity_id} and todo {todo}")
    else:
        click.echo(f"Association not found")
