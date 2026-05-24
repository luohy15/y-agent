import json

from fastapi import APIRouter, HTTPException, Query, Request

from agent.config import resolve_vm_config
from agent.tool_base import Tool
from storage.service import finance_holding as holding_service
from storage.service import finance_price as price_service
from storage.service import finance_snapshot as snapshot_service
from storage.service import finance_transaction as transaction_service
from storage.service.finance_queries import CANONICAL_QUERIES, FinanceQuery, beancount_cmd

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


async def _get_cached_or_live(user_id: int, vm_name: str | None, query: FinanceQuery):
    effective_vm_name = vm_name or ""
    cached = snapshot_service.get_or_none(
        user_id=user_id,
        vm_name=effective_vm_name,
        view=query.view,
        time_filter=query.time_filter,
        history=query.history,
        granularity=query.granularity,
        convert=query.convert,
    )
    if cached and snapshot_service.is_fresh(cached):
        cached.source = "cache"
        return cached.to_dict()

    output = await _exec(user_id, beancount_cmd(query), timeout=60, vm_name=vm_name)
    payload = _parse_json(output)
    snapshot = snapshot_service.upsert_payload(
        user_id=user_id,
        vm_name=effective_vm_name,
        view=query.view,
        payload=payload,
        source="live",
        time_filter=query.time_filter,
        history=query.history,
        granularity=query.granularity,
        convert=query.convert,
    )
    return snapshot.to_dict()


async def _warm_canonical(user_id: int, vm_name: str | None):
    synced = 0
    failed = 0
    for query in CANONICAL_QUERIES:
        try:
            await _get_cached_or_live(user_id, vm_name, query)
            synced += 1
        except Exception:
            failed += 1
    return {"user_id": user_id, "vm_name": vm_name or "", "synced": synced, "failed": failed}


async def _warm_normalized(user_id: int, vm_name: str | None):
    effective_vm_name = vm_name or ""
    synced = 0
    failed = 0
    commands = [
        ("holdings", ["y", "beancount", "holdings"], lambda payload: holding_service.append_snapshot(user_id, effective_vm_name, holding_service.rows_from_holdings_payload(payload), source="live")),
        ("transactions", ["y", "beancount", "transactions"], lambda payload: transaction_service.replace_for(user_id, effective_vm_name, payload, source="live")),
        ("prices", ["y", "beancount", "prices"], lambda payload: price_service.replace_for(user_id, effective_vm_name, payload, source="live")),
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
    query = FinanceQuery("balance_sheet", "balance-sheet", time_filter=time, history=history, granularity=granularity if history else "", convert=convert)
    return await _get_cached_or_live(user_id, vm_name, query)


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
    query = FinanceQuery("income_statement", "income-statement", time_filter=time, history=history, granularity=granularity if history else "", convert=convert)
    return await _get_cached_or_live(user_id, vm_name, query)


@router.get("/positions")
async def positions(
    request: Request,
    vm_name: str = Query(None),
    at: str = Query(None),
):
    user_id = _get_user_id(request)
    rows = holding_service.list_at(user_id, vm_name or "", at) if at else holding_service.list_for(user_id, vm_name or "")
    return _envelope(rows)


@router.get("/transactions")
async def transactions(
    request: Request,
    vm_name: str = Query(None),
    symbol: str = Query(None),
    limit: int = Query(500),
):
    user_id = _get_user_id(request)
    return _envelope(transaction_service.list_for(user_id, vm_name or "", symbol=symbol, limit=limit))


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
    query = FinanceQuery("fire_progress", "fire-progress", convert="USD")
    return await _get_cached_or_live(user_id, vm_name, query)


@router.post("/refresh")
async def refresh(request: Request, vm_name: str = Query(None)):
    user_id = _get_user_id(request)
    snapshot_service.invalidate_user(user_id, vm_name or "")
    result = await _warm_canonical(user_id, vm_name)
    normalized = await _warm_normalized(user_id, vm_name)
    return {"status": "ok", **result, **normalized}
