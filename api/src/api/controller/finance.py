import json

from fastapi import APIRouter, HTTPException, Query, Request

from agent.config import resolve_vm_config
from agent.tool_base import Tool

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


def _beancount_cmd(subcommand: str, time: str, history: bool, granularity: str, convert: str) -> list[str]:
    cmd = ["y", "beancount"]
    if time:
        cmd += ["--time", time]
    if history:
        cmd += ["--history", "--granularity", granularity]
    if convert:
        cmd += ["--convert", convert]
    cmd.append(subcommand)
    return cmd


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
    cmd = _beancount_cmd("balance-sheet", time, history, granularity, convert)
    output = await _exec(user_id, cmd, timeout=60, vm_name=vm_name)
    return _parse_json(output)

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
    cmd = _beancount_cmd("income-statement", time, history, granularity, convert)
    output = await _exec(user_id, cmd, timeout=60, vm_name=vm_name)
    return _parse_json(output)

@router.get("/position")
async def position(
    request: Request,
    convert: str = Query("USD"),
    vm_name: str = Query(None),
):
    user_id = _get_user_id(request)
    cmd = _beancount_cmd("position", "", False, "monthly", convert)
    output = await _exec(user_id, cmd, timeout=60, vm_name=vm_name)
    return _parse_json(output)

@router.get("/holdings")
async def holdings(
    request: Request,
    vm_name: str = Query(None),
):
    user_id = _get_user_id(request)
    cmd = _beancount_cmd("holdings", "", False, "monthly", "")
    output = await _exec(user_id, cmd, timeout=60, vm_name=vm_name)
    return _parse_json(output)
