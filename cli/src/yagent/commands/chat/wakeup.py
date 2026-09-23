import click
import httpx
from tabulate import tabulate

from yagent.api_client import api_request
from yagent.time_util import utc_to_local


def _echo_http_error(e: httpx.HTTPStatusError):
    try:
        detail = e.response.json().get("detail", "")
    except Exception:
        detail = e.response.text
    click.echo(f"Error: {detail}", err=True)
    raise SystemExit(1)


@click.group("wakeup")
def chat_wakeup_group():
    """Manage registered scheduled chat wakeups (`y chat --at`)."""


@chat_wakeup_group.command("list")
@click.option("--trace-id", default=None, help="Filter to wakeups on this trace")
@click.option("--all", "show_all", is_flag=True, help="Include delivered/cancelled wakeups (default: pending/accepted only)")
@click.option("--limit", "-l", default=50, help="Max results")
def wakeup_list(trace_id, show_all, limit):
    """List this account's registered wakeups."""
    params = {"limit": limit}
    if trace_id:
        params["trace_id"] = trace_id
    if show_all:
        params["all"] = True
    try:
        resp = api_request("GET", "/api/chat/wakeup", params=params)
    except httpx.HTTPStatusError as e:
        _echo_http_error(e)
    wakeups = resp.json()
    if not wakeups:
        click.echo("No wakeups found")
        return

    table = []
    for w in wakeups:
        due_at = utc_to_local(_unix_to_utc_iso(w["due_at_unix"]))
        table.append([w["wakeup_id"], w["chat_id"], w["trace_id"], due_at, w["status"]])
    click.echo(tabulate(table, headers=["ID", "Chat", "Trace", "Due At", "Status"], tablefmt="simple"))


def _unix_to_utc_iso(unix_ms: int) -> str:
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(unix_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@chat_wakeup_group.command("cancel")
@click.argument("wakeup_id")
def wakeup_cancel(wakeup_id):
    """Cancel a pending wakeup."""
    try:
        resp = api_request("POST", "/api/chat/wakeup/cancel", json={"wakeup_id": wakeup_id})
    except httpx.HTTPStatusError as e:
        _echo_http_error(e)
    w = resp.json()
    click.echo(f"Cancelled wakeup {w['wakeup_id']} (chat {w['chat_id']})")
