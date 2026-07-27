import click
from tabulate import tabulate

from yagent.api_client import api_request
from yagent.time_filter import collect_time_params, time_filter_options
from yagent.time_util import utc_to_local


@click.command("list")
@click.option("--dismissed", "dismissed_flag", is_flag=True, default=False, help="Only dismissed")
@click.option("--active", "active_flag", is_flag=True, default=False, help="Only active (default)")
@click.option("--all", "all_flag", is_flag=True, default=False, help="Active + dismissed")
@click.option("--category", default=None, help="Filter by free-form category")
@click.option("--query", "-q", default=None, help="Search original/corrected/explanation")
@time_filter_options
@click.option("--limit", "-l", default=50, help="Max results")
@click.option("--offset", default=0, help="Offset")
def english_list(
    dismissed_flag,
    active_flag,
    all_flag,
    category,
    query,
    on,
    from_,
    to,
    created_on,
    created_from,
    created_to,
    updated_on,
    updated_from,
    updated_to,
    limit,
    offset,
):
    """List corrections. Canonical time field: created_at. Default: active only."""
    flags = sum(bool(x) for x in (dismissed_flag, active_flag, all_flag))
    if flags > 1:
        raise click.UsageError("--dismissed, --active, and --all are mutually exclusive")

    params = {"limit": limit, "offset": offset}
    if dismissed_flag:
        params["dismissed"] = "true"
    elif all_flag:
        pass  # no dismissed filter
    else:
        # default: active only
        params["dismissed"] = "false"
    if category:
        params["category"] = category
    if query:
        params["query"] = query
    params.update(
        collect_time_params(
            on=on,
            from_=from_,
            to=to,
            created_on=created_on,
            created_from=created_from,
            created_to=created_to,
            updated_on=updated_on,
            updated_from=updated_from,
            updated_to=updated_to,
        )
    )

    resp = api_request("GET", "/api/english/list", params=params)
    rows = resp.json()
    if not rows:
        click.echo("No corrections found")
        return

    table = []
    for r in rows:
        msg_at = utc_to_local(r["message_at"]) if r.get("message_at") else "-"
        cats = ",".join(r.get("error_categories") or []) or "-"
        original = (r.get("original_text") or "").replace("\n", " ")
        if len(original) > 48:
            original = original[:45] + "..."
        table.append(
            [
                r["correction_id"],
                "yes" if r.get("dismissed") else "no",
                cats,
                msg_at,
                original,
            ]
        )
    click.echo(
        tabulate(
            table,
            headers=["ID", "Dismissed", "Categories", "Message At", "Original"],
            tablefmt="simple",
        )
    )
