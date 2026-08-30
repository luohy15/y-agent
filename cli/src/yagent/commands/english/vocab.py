import click
from tabulate import tabulate

from yagent.api_client import api_request
from yagent.time_filter import collect_time_params, time_filter_options

TIER_MAX_RANK = {"3k": 3000, "5k": 5000, "10k": 10000}


@click.group("vocab")
def english_vocab_group():
    """Manage the English vocabulary scan-and-mark inventory."""
    pass


@english_vocab_group.command("seed")
def vocab_seed():
    """Seed the frequency-ranked top-10k list for the current user (idempotent)."""
    resp = api_request("POST", "/api/english/vocab/seed")
    row = resp.json()
    click.echo(
        f"Seeded vocabulary inserted={row['inserted']} updated={row['updated']} total={row['total']}"
    )


@english_vocab_group.command("list")
@click.option("--status", "-s", default=None, help="Filter by status (unseen/known/unknown)")
@click.option("--tier", type=click.Choice(["3k", "5k", "10k"]), default=None, help="Filter by cumulative rank band")
@time_filter_options
@click.option("--limit", "-l", default=50, help="Max results")
@click.option("--offset", default=0, help="Offset")
def vocab_list(
    status,
    tier,
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
    """List vocabulary words. Canonical time field: marked_at."""
    params = {"limit": limit, "offset": offset}
    if status:
        params["status"] = status
    if tier:
        params["max_rank"] = TIER_MAX_RANK[tier]
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
    resp = api_request("GET", "/api/english/vocab/list", params=params)
    rows = resp.json()
    if not rows:
        click.echo("No vocabulary words found")
        return
    table = []
    for r in rows:
        table.append([
            r.get("word_id"),
            r.get("rank"),
            r.get("word"),
            r.get("status"),
            r.get("marked_at") or "-",
        ])
    click.echo(tabulate(table, headers=["ID", "Rank", "Word", "Status", "Marked At"], tablefmt="simple"))


@english_vocab_group.command("mark")
@click.argument("words", nargs=-1, required=True)
@click.option("--unknown", "status", flag_value="unknown")
@click.option("--known", "status", flag_value="known")
@click.option("--unseen", "status", flag_value="unseen")
def vocab_mark(words, status):
    """Mark one or more words known / unknown / unseen."""
    if not status:
        raise click.UsageError("one of --unknown, --known, --unseen is required")
    resp = api_request(
        "POST",
        "/api/english/vocab/mark",
        json={"status": status, "words": list(words)},
    )
    rows = resp.json()
    click.echo(f"Marked {len(rows)} word(s) {status}")


@english_vocab_group.command("stats")
def vocab_stats():
    """Show per-tier vocabulary progress."""
    resp = api_request("GET", "/api/english/vocab/stats")
    data = resp.json()
    reviewed = data.get("reviewed") or 0
    total = data.get("total") or 0
    next_rank = data.get("next_unseen_rank")
    click.echo(f"Reviewed {reviewed} / {total}" + (f"  next unseen rank {next_rank}" if next_rank is not None else "  scan complete"))
    tiers = data.get("tiers") or []
    if not tiers:
        return
    table = []
    for t in tiers:
        table.append([
            t.get("label"),
            t.get("reviewed"),
            t.get("total"),
            f"{t.get('percent')}%",
            t.get("known"),
            t.get("unknown"),
        ])
    click.echo(tabulate(table, headers=["Tier", "Reviewed", "Total", "Percent", "Known", "Unknown"], tablefmt="simple"))
