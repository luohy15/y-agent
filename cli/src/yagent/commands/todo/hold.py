from datetime import datetime

import click
from yagent.api_client import api_request
from yagent.time_util import resolve_due_at


def _options(fn):
    fn = click.option("--clear", is_flag=True, help="Clear the declared machine wait")(fn)
    fn = click.option("--until", default=None, help="Deadline: +Nm, +Nh or ISO timestamp (default +6h, max +24h)")(fn)
    fn = click.option("--chat", "chat_id", default=None, help="Same-owner same-todo callback chat ID")(fn)
    fn = click.option("--on", default=None, help="Machine dependency (at most 120 characters)")(fn)
    return click.argument("todo_id")(fn)


def _run(todo_id, on, chat_id, until, clear):
    """Declare a bounded machine wait without leaving active status."""
    body = {"todo_id": todo_id}
    if clear:
        if any(value is not None for value in (on, chat_id, until)):
            raise click.UsageError("--clear cannot be combined with --on, --chat or --until")
        body["clear"] = True
    else:
        if not on or not on.strip() or len(on) > 120 or not chat_id:
            raise click.UsageError("--on (1-120 characters) and --chat are required")
        body.update(on=on, chat_id=chat_id)
        if until is not None:
            try:
                due = resolve_due_at(until)
                body["until"] = int(datetime.fromisoformat(due.replace("Z", "+00:00")).timestamp() * 1000)
            except (ValueError, OverflowError) as exc:
                raise click.UsageError(str(exc).replace("--at", "--until")) from exc
    todo = api_request("POST", "/api/todo/wait", json=body).json()
    click.echo(f"Todo {todo['todo_id']}: {todo['status']} (hold {'cleared' if clear else 'declared'})")


todo_hold = click.command("hold")(_options(_run))
todo_wait = click.command("wait", hidden=True)(_options(_run))
