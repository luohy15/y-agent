"""`y claude usage [--json]` — scrape Claude Code subscription limit-window usage.

Spins up an ephemeral Claude Code TUI on the EC2 subscription-login box, runs the
`/usage` overlay, and reports the three limit windows (current session / current
week all-models / current week Sonnet-only) as a friendly table or, with
`--json`, the raw envelope.
"""

import asyncio
import json
from datetime import datetime, timezone

import click

from storage.service.user import get_cli_user_id
from storage.service import vm_config as vm_service
from agent import config as agent_config
from agent.claude_usage import read_claude_usage


_WINDOW_ROWS = (
    ("session", "Current session"),
    ("week_all", "Current week (all models)"),
    ("week_sonnet", "Current week (Sonnet only)"),
)


@click.command("usage")
@click.option("--user-id", type=int, default=None, help="Numeric user.id to resolve the VM for")
@click.option("--vm-name", default=None, help="VM config name (defaults to the user's default VM)")
@click.option("--work-dir", default=None, help="Override the TUI launch directory")
@click.option("--json", "as_json", is_flag=True, help="Output the raw JSON envelope instead of a table")
def usage(user_id: int | None, vm_name: str | None, work_dir: str | None, as_json: bool):
    """Scrape Claude Code 5h + weekly limit-window usage via the /usage TUI overlay."""
    target_user_id = user_id or get_cli_user_id()
    vm_config = agent_config.resolve_vm_config(target_user_id, vm_name, work_dir=work_dir)

    result = asyncio.run(read_claude_usage(vm_config))

    envelope = {
        "data": {key: result.get(key) for key, _ in _WINDOW_ROWS},
        "parse_ok": result.get("parse_ok", False),
        "source": "claude_tui",
        "raw": result.get("raw", ""),
    }

    # Best-effort write-through to the sidebar cache (vm_config.claude_usage). A
    # cache-write failure must never break the scrape/alert output.
    try:
        cached = dict(envelope)
        cached.pop("raw", None)
        cached["scraped_at"] = datetime.now(timezone.utc).isoformat()
        vm_service.save_claude_usage(target_user_id, vm_config.name, cached)
    except Exception as exc:
        click.echo(f"warning: failed to cache claude usage: {exc}", err=True)

    if as_json:
        click.echo(json.dumps(envelope))
        return

    if not envelope["parse_ok"]:
        click.echo("parse failed — raw pane:")
        click.echo(envelope["raw"])
        return

    click.echo(f"{'Window':<28} {'Used':>6}  Resets")
    click.echo("-" * 60)
    for key, label in _WINDOW_ROWS:
        win = envelope["data"].get(key) or {}
        percent = win.get("percent")
        reset = win.get("reset") or "-"
        pct = f"{percent}%" if percent is not None else "-"
        click.echo(f"{label:<28} {pct:>6}  {reset}")
