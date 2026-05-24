import json

from fastapi import APIRouter, HTTPException, Query, Request

from agent.config import resolve_vm_config
from agent.tool_base import Tool
from storage.service import finance_snapshot as snapshot_service
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


@router.get("/holdings")
async def holdings(
    request: Request,
    vm_name: str = Query(None),
):
    user_id = _get_user_id(request)
    query = FinanceQuery("holdings", "holdings")
    return await _get_cached_or_live(user_id, vm_name, query)


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
    return {"status": "ok", **result}
