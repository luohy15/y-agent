"""Scheduled normalized finance table warmer."""

import json
from typing import Optional

from agent.config import resolve_vm_config
from agent.tool_base import Tool
from loguru import logger

from storage.service import finance_holding as holding_service
from storage.service import finance_price as price_service
from storage.service import finance_transaction as transaction_service
from storage.service import user as user_service
from storage.service import vm_config as vm_config_service


class _CmdRunner(Tool):
    name = "_cmd_runner"
    description = ""
    parameters = {}

    async def execute(self, arguments):
        pass


async def sync_normalized(user_id: int, vm_name: str, runner: _CmdRunner, source: str = "sync") -> tuple[int, int]:
    synced = 0
    failed = 0
    commands = [
        ("holdings", ["y", "beancount", "holdings"], lambda payload: holding_service.append_snapshot(user_id, holding_service.rows_from_holdings_payload(payload), source=source)),
        ("transactions", ["y", "beancount", "transactions"], lambda payload: transaction_service.replace_for(user_id, payload, source=source)),
        ("prices", ["y", "beancount", "prices"], lambda payload: price_service.replace_for(payload, source=source)),
        ("fire-config", ["y", "beancount", "fire-config", "push", "--user-id", str(user_id), "--vm-name", vm_name], lambda payload: None),
    ]
    for name, cmd, writer in commands:
        try:
            output = await runner.run_cmd(cmd, timeout=60)
            writer(json.loads(output))
            synced += 1
        except Exception as exc:
            failed += 1
            logger.exception("[finance] normalized sync failed user_id={} vm_name={} name={}: {}", user_id, vm_name, name, exc)
    return synced, failed


async def warm_finance_tables(user_id: int, vm_name: Optional[str] = None, source: str = "sync") -> dict:
    effective_vm_name = vm_name or ""
    vm_config = resolve_vm_config(user_id, vm_name or None)
    runner = _CmdRunner(vm_config)
    synced, failed = await sync_normalized(user_id, effective_vm_name, runner, source=source)
    return {"user_id": user_id, "vm_name": effective_vm_name, "synced": synced, "failed": failed}


async def handle_sync_finance() -> dict:
    results = []
    for user_row in user_service.list_users():
        configs = vm_config_service.list_configs(user_row.id)
        if not configs:
            continue
        seen = set()
        for config in configs:
            vm_name = "" if config.name == "default" else (config.name or "")
            if vm_name in seen:
                continue
            seen.add(vm_name)
            results.append(await warm_finance_tables(user_row.id, vm_name=vm_name))
    synced = sum(row["synced"] for row in results)
    failed = sum(row["failed"] for row in results)
    return {"status": "ok", "synced": synced, "failed": failed, "results": results}
