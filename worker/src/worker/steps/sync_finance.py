"""Scheduled finance snapshot warmer."""

import json
from typing import Optional

from agent.config import resolve_vm_config
from agent.tool_base import Tool
from loguru import logger

from storage.service import finance_snapshot as snapshot_service
from storage.service import user as user_service
from storage.service import vm_config as vm_config_service
from storage.service.finance_queries import CANONICAL_QUERIES, FinanceQuery, beancount_cmd


class _CmdRunner(Tool):
    name = "_cmd_runner"
    description = ""
    parameters = {}

    async def execute(self, arguments):
        pass


async def sync_query(user_id: int, vm_name: str, query: FinanceQuery, runner: _CmdRunner, source: str = "sync") -> bool:
    output = await runner.run_cmd(beancount_cmd(query), timeout=60)
    payload = json.loads(output)
    snapshot_service.upsert_payload(
        user_id=user_id,
        vm_name=vm_name,
        view=query.view,
        payload=payload,
        source=source,
        time_filter=query.time_filter,
        history=query.history,
        granularity=query.granularity,
        convert=query.convert,
    )
    return True


async def warm_canonical_snapshots(user_id: int, vm_name: Optional[str] = None, source: str = "sync") -> dict:
    effective_vm_name = vm_name or ""
    vm_config = resolve_vm_config(user_id, vm_name or None)
    runner = _CmdRunner(vm_config)
    synced = 0
    failed = 0
    for query in CANONICAL_QUERIES:
        try:
            await sync_query(user_id, effective_vm_name, query, runner, source=source)
            synced += 1
        except Exception as exc:
            failed += 1
            logger.exception(
                "[finance] sync failed user_id={} vm_name={} view={} time={} history={} granularity={} convert={}: {}",
                user_id,
                effective_vm_name,
                query.view,
                query.time_filter,
                query.history,
                query.granularity,
                query.convert,
                exc,
            )
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
            results.append(await warm_canonical_snapshots(user_row.id, vm_name=vm_name))
    synced = sum(row["synced"] for row in results)
    failed = sum(row["failed"] for row in results)
    return {"status": "ok", "synced": synced, "failed": failed, "results": results}
