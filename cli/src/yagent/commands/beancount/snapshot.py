import json

import click

from storage.service import finance_holding as holding_service
from storage.service import finance_price as price_service
from storage.service import finance_transaction as transaction_service
from storage.service.user import get_cli_user_id
from yagent.commands.beancount.fire_progress import _load_fire_config
from storage.service import finance_config as finance_config_service


@click.command("snapshot")
@click.option("--user-id", type=int, default=None, help="Numeric user.id to write snapshots for")
@click.option("--vm-name", default="", help="Snapshot VM name key")
@click.pass_context
def snapshot(ctx, user_id: int | None, vm_name: str):
    """Refresh normalized finance tables into the local database."""
    from click.testing import CliRunner
    from yagent.commands.beancount.click import beancount_group

    target_user_id = user_id or get_cli_user_id()
    runner = CliRunner()
    synced = 0
    normalized = [
        ("holdings", ["holdings"], lambda payload: holding_service.append_snapshot(target_user_id, vm_name, holding_service.rows_from_holdings_payload(payload), source="cli")),
        ("transactions", ["transactions"], lambda payload: transaction_service.replace_for(target_user_id, vm_name, payload, source="cli")),
        ("prices", ["prices"], lambda payload: price_service.replace_for(target_user_id, vm_name, payload, source="cli")),
    ]
    for _, args, writer in normalized:
        result = runner.invoke(beancount_group, args, catch_exceptions=False)
        writer(json.loads(result.output))
        synced += 1
    cfg, source = _load_fire_config()
    finance_config_service.set_for(target_user_id, vm_name, {
        "monthly_expense_usd": cfg.get("monthly_expense_usd"),
        "withdrawal_rate": cfg.get("withdrawal_rate"),
        "target_usd": cfg.get("target_usd"),
        "config_source": source,
    })
    total = len(normalized)
    click.echo(f"synced {synced}/{total} views + fire-config")
