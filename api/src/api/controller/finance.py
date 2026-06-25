import json

from fastapi import APIRouter, HTTPException, Query, Request

from storage.service import finance_holding as holding_service
from storage.service import finance_derived as derived_service
from storage.service import finance_price as price_service
from storage.service import finance_realtime_quote as realtime_quote_service
from storage.service import finance_transaction as transaction_service

router = APIRouter(prefix="/finance")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


# Lazily build the Tool subclass so the agent layer (paramiko/cryptography/boto3)
# stays out of the API import path until /finance endpoints are actually hit.
_cmd_runner_cls = None


def _get_cmd_runner_cls():
    global _cmd_runner_cls
    if _cmd_runner_cls is None:
        from agent.tool_base import Tool

        class _CmdRunner(Tool):
            name = "_cmd_runner"
            description = ""
            parameters = {}

            async def execute(self, arguments):
                pass

        _cmd_runner_cls = _CmdRunner
    return _cmd_runner_cls


async def _exec(user_id: int, cmd: list[str], timeout: float = 30, vm_name: str = None) -> str:
    from agent.config import resolve_vm_config
    vm_config = resolve_vm_config(user_id, vm_name)
    runner = _get_cmd_runner_cls()(vm_config)
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
        ("holdings", ["y", "finance", "beancount", "holdings"], lambda payload: holding_service.append_snapshot(user_id, holding_service.rows_from_holdings_payload(payload), source="live")),
        ("transactions", ["y", "finance", "beancount", "transactions"], lambda payload: transaction_service.replace_for(user_id, payload, source="live")),
        ("prices", ["y", "finance", "beancount", "prices"], lambda payload: price_service.replace_for(payload, source="live")),
        ("fire-config", ["y", "finance", "beancount", "fire-config", "push", "--user-id", str(user_id), "--vm-name", effective_vm_name], lambda payload: None),
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


def _envelope_result(result, source: str = "derived"):
    return {"data": result.data, **result.meta, "synced_at": result.synced_at or "", "source": source}


def _normalize_realtime_symbols(symbols: str) -> list[str]:
    normalized = sorted({symbol.strip().upper() for symbol in (symbols or "").split(",") if symbol.strip()})
    return normalized[:50]


@router.get("/balance-sheet")
async def balance_sheet(
    request: Request,
    time: str = Query(""),
    history: bool = Query(False),
    granularity: str = Query("monthly"),
    convert: str = Query("USD"),
    breakdown: str | None = Query(None),
    risky_only: bool = Query(False),
    vm_name: str = Query(None),
):
    user_id = _get_user_id(request)
    if breakdown in ("positions", "categories"):
        result = derived_service.balance_sheet_positions(user_id, vm_name or "", time, granularity, convert or None, risky_only=risky_only)
        return _envelope_result(result)
    result = derived_service.balance_sheet(user_id, vm_name or "", time, history, granularity, convert or None)
    return _envelope_result(result)


@router.get("/income-statement")
async def income_statement(
    request: Request,
    time: str = Query("month"),
    history: bool = Query(False),
    granularity: str = Query("monthly"),
    convert: str = Query("USD"),
    breakdown: str | None = Query(None),
    vm_name: str = Query(None),
):
    user_id = _get_user_id(request)
    if breakdown == "categories":
        result = derived_service.income_statement_categories(user_id, vm_name or "", time, granularity, convert or None)
        return _envelope_result(result)
    result = derived_service.income_statement(user_id, vm_name or "", time, history, granularity, convert or None)
    return _envelope_dict(result.data, result.synced_at)


@router.get("/investment-returns")
async def investment_returns(
    request: Request,
    time: str = Query("ytd"),
    history: bool = Query(False),
    granularity: str = Query("monthly"),
    convert: str = Query("USD"),
    vm_name: str = Query(None),
):
    user_id = _get_user_id(request)
    result = derived_service.investment_returns(user_id, vm_name or "", time, history, granularity, convert or None)
    return _envelope_result(result)


@router.get("/holdings")
async def holdings(
    request: Request,
    vm_name: str = Query(None),
    at: str = Query(None),
    risky_only: bool = Query(False),
    base_currency: str = Query("USD"),
):
    user_id = _get_user_id(request)
    result = derived_service.holding_positions(user_id, vm_name or "", at, risky_only=risky_only, base_currency=base_currency)
    return _envelope_result(result, source="db")


@router.get("/realtime-quotes")
async def realtime_quotes(
    symbols: str = Query(""),
    vm_name: str = Query(None),
):
    del vm_name
    normalized = _normalize_realtime_symbols(symbols)
    if not realtime_quote_service.api_key():
        raise HTTPException(status_code=503, detail="ALPHAVANTAGE_API_KEY is not configured")
    result = realtime_quote_service.fetch_bulk(normalized)
    fetched_at = result.fetched_at.isoformat().replace("+00:00", "Z") if result.fetched_at else ""
    return {
        "data": {symbol: quote.to_dict() for symbol, quote in result.quotes.items()},
        "fetched_at": fetched_at,
        "source": result.source,
    }


@router.get("/transactions")
async def transactions(
    request: Request,
    vm_name: str = Query(None),
    symbol: str = Query(None),
    limit: int = Query(500),
):
    user_id = _get_user_id(request)
    rows = transaction_service.list_entries_for(user_id, symbol=symbol, limit=limit)
    synced_at = rows[0].get("synced_at", "") if rows else ""
    return {"data": rows, "synced_at": synced_at, "source": "db"}


@router.get("/prices")
async def prices(
    vm_name: str = Query(None),
    symbol: str = Query(None),
    time: str = Query("year to day-1"),
    limit: int = Query(1000),
):
    from_date, to_date = derived_service.parse_time_range(time)
    return _envelope(price_service.list_for(symbol=symbol, from_date=str(from_date) if from_date else None, to_date=str(to_date) if to_date else None, limit=limit))


@router.get("/fire-progress")
async def fire_progress(
    request: Request,
    vm_name: str = Query(None),
):
    user_id = _get_user_id(request)
    result = derived_service.fire_progress(user_id, vm_name or "")
    return _envelope_result(result)


@router.get("/quick-stats")
async def quick_stats(
    request: Request,
    vm_name: str = Query(None),
):
    user_id = _get_user_id(request)
    result = derived_service.quick_stats(user_id, vm_name or "")
    return _envelope_result(result)


@router.get("/large-transactions")
async def large_transactions(
    request: Request,
    vm_name: str = Query(None),
    threshold: float = Query(100.0),
    limit: int = Query(200),
):
    user_id = _get_user_id(request)
    result = derived_service.large_transactions(user_id, vm_name or "", threshold_usd=threshold, limit=limit)
    return _envelope_dict(result.data, result.synced_at)


@router.post("/refresh")
async def refresh(request: Request, vm_name: str = Query(None)):
    user_id = _get_user_id(request)
    normalized = await _warm_normalized(user_id, vm_name)
    return {"status": "ok", "user_id": user_id, "vm_name": vm_name or "", **normalized}
