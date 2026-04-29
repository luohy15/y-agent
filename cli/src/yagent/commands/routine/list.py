import click
from tabulate import tabulate

from yagent.api_client import api_request
from yagent.time_util import utc_to_local


def _format_target(r: dict) -> str:
    if r.get("target_topic"):
        return f"topic={r['target_topic']}"
    if r.get("target_skill"):
        return f"skill={r['target_skill']}"
    return "-"


@click.command('list')
@click.option('--enabled', 'enabled_flag', is_flag=True, default=False, help='Only enabled routines')
@click.option('--disabled', 'disabled_flag', is_flag=True, default=False, help='Only disabled routines')
@click.option('--limit', '-l', default=50, help='Max results')
def routine_list(enabled_flag, disabled_flag, limit):
    """List routines."""
    if enabled_flag and disabled_flag:
        raise click.UsageError("--enabled and --disabled are mutually exclusive")

    params = {"limit": limit}
    if enabled_flag:
        params["enabled"] = "true"
    elif disabled_flag:
        params["enabled"] = "false"

    resp = api_request("GET", "/api/routine/list", params=params)
    routines = resp.json()
    if not routines:
        click.echo("No routines found")
        return

    table = []
    for r in routines:
        last_run = utc_to_local(r["last_run_at"]) if r.get("last_run_at") else "-"
        status = r.get("last_run_status") or "-"
        table.append([
            r["routine_id"],
            r["name"],
            r["schedule"],
            _format_target(r),
            "yes" if r.get("enabled") else "no",
            last_run,
            status,
        ])
    click.echo(tabulate(
        table,
        headers=["ID", "Name", "Schedule", "Target", "Enabled", "Last Run", "Status"],
        tablefmt="simple",
    ))
