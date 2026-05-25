import json

from fastapi import APIRouter, HTTPException, Query, Request

from agent.config import resolve_vm_config
from agent.tool_base import Tool
from api import service_finance_derived as derived_service
from storage.service import finance_holding as holding_service
from storage.service import finance_price as price_service
from storage.service import finance_transaction as transaction_service

router = APIRouter(prefix="/finance")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


class _CmdRunner(Tool):
    name = "_cmd_runner"
    description = ""
    parameters = {}

    async def execute(self, arguments):
        pass


async def _exec(user_id: int, cmd: list[str], timeout: float = 30, vm_name: str = None) -> str:
    vm_config = resolve_vm_config(user_id, vm_name)
    runner = _CmdRunner(vm_config)
    try:
        return await runner.run_cmd(cmd, timeout=timeout)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


def _parse_json(output: str):
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail=f"Script failed:\n{output}")


async def _warm_normalized(user_id: int, vm_name: str | None):
    effective_vm_name = vm_name or ""
    synced = 0
    failed = 0
    commands = [
        ("holdings", ["y", "beancount", "holdings"], lambda payload: holding_service.append_snapshot(user_id, effective_vm_name, holding_service.rows_from_holdings_payload(payload), source="live")),
        ("transactions", ["y", "beancount", "transactions"], lambda payload: transaction_service.replace_for(user_id, effective_vm_name, payload, source="live")),
        ("prices", ["y", "beancount", "prices"], lambda payload: price_service.replace_for(user_id, effective_vm_name, payload, source="live")),
        ("fire-config", ["y", "beancount", "fire-config", "push", "--user-id", str(user_id), "--vm-name", effective_vm_name], lambda payload: None),
    ]
    for _, cmd, writer in commands:
        try:
            output = await _exec(user_id, cmd, timeout=60, vm_name=vm_name)
            writer(_parse_json(output))
            synced += 1
        except Exception:
            failed += 1
    return {"normalized_synced": synced, "normalized_failed": failed}


def _envelope(rows, source: str = "db"):
    synced_at = rows[0].synced_at if rows else ""
    return {"data": [row.to_dict() for row in rows], "synced_at": synced_at, "source": source}


def _envelope_dict(data, synced_at: str, source: str = "derived"):
    return {"data": data, "synced_at": synced_at or "", "source": source}


@router.get("/balance-sheet")
async def balance_sheet(
    request: Request,
    time: str = Query(""),
    history: bool = Query(False),
    granularity: str = Query("monthly"),
    convert: str = Query("USD"),
    vm_name: str = Query(None),
):
    user_id = _get_user_id(request)
    result = derived_service.balance_sheet(user_id, vm_name or "", time, history, granularity, convert or None)
    return _envelope_dict(result.data, result.synced_at)


@router.get("/income-statement")
async def income_statement(
    request: Request,
    time: str = Query("month"),
    history: bool = Query(False),
    granularity: str = Query("monthly"),
    convert: str = Query("USD"),
    vm_name: str = Query(None),
):
    user_id = _get_user_id(request)
    result = derived_service.income_statement(user_id, vm_name or "", time, history, granularity, convert or None)
    return _envelope_dict(result.data, result.synced_at)


@router.get("/positions")
async def positions(
    request: Request,
    vm_name: str = Query(None),
    at: str = Query(None),
    risky_only: bool = Query(False),
):
    user_id = _get_user_id(request)
    rows = holding_service.list_at(user_id, vm_name or "", at, risky_only=risky_only) if at else holding_service.list_for(user_id, vm_name or "", risky_only=risky_only)
    return _envelope(rows)


@router.get("/transactions")
async def transactions(
    request: Request,
    vm_name: str = Query(None),
    symbol: str = Query(None),
    limit: int = Query(500),
):
    user_id = _get_user_id(request)
    rows = transaction_service.list_entries_for(user_id, vm_name or "", symbol=symbol, limit=limit)
    synced_at = rows[0].get("synced_at", "") if rows else ""
    return {"data": rows, "synced_at": synced_at, "source": "db"}


@router.get("/prices")
async def prices(
    request: Request,
    vm_name: str = Query(None),
    symbol: str = Query(None),
    from_: str = Query(None, alias="from"),
    limit: int = Query(1000),
):
    user_id = _get_user_id(request)
    return _envelope(price_service.list_for(user_id, vm_name or "", symbol=symbol, from_date=from_, limit=limit))


@router.get("/fire-progress")
async def fire_progress(
    request: Request,
    vm_name: str = Query(None),
):
    user_id = _get_user_id(request)
    result = derived_service.fire_progress(user_id, vm_name or "")
    return _envelope_dict(result.data, result.synced_at)


@router.post("/refresh")
async def refresh(request: Request, vm_name: str = Query(None)):
    user_id = _get_user_id(request)
    normalized = await _warm_normalized(user_id, vm_name)
    return {"status": "ok", "user_id": user_id, "vm_name": vm_name or "", **normalized}
