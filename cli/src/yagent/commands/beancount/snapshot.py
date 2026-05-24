import json

import click

from storage.service import finance_snapshot as snapshot_service
from storage.service.user import get_cli_user_id
from storage.service.finance_queries import CANONICAL_QUERIES


@click.command("snapshot")
@click.option("--user-id", type=int, default=None, help="Numeric user.id to write snapshots for")
@click.option("--vm-name", default="", help="Snapshot VM name key")
@click.pass_context
def snapshot(ctx, user_id: int | None, vm_name: str):
    """Refresh canonical finance snapshots into the local database."""
    from click.testing import CliRunner
    from yagent.commands.beancount.click import beancount_group

    target_user_id = user_id or get_cli_user_id()
    runner = CliRunner()
    synced = 0
    failed = 0
    for query in CANONICAL_QUERIES:
        args = []
        if query.time_filter:
            args += ["--time", query.time_filter]
        if query.history:
            args += ["--history", "--granularity", query.granularity or "monthly"]
        if query.convert:
            args += ["--convert", query.convert]
        args.append(query.subcommand)
        result = runner.invoke(beancount_group, args, catch_exceptions=False)
        payload = json.loads(result.output)
        snapshot_service.upsert_payload(
            user_id=target_user_id,
            vm_name=vm_name,
            view=query.view,
            payload=payload,
            source="cli",
            time_filter=query.time_filter,
            history=query.history,
            granularity=query.granularity,
            convert=query.convert,
        )
        synced += 1
    total = len(CANONICAL_QUERIES)
    click.echo(f"synced {synced}/{total} views" + (f", failed {failed}" if failed else ""))
