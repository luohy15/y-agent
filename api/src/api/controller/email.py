import asyncio
import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel

from agent.config import resolve_vm_config
from agent.ec2_wake import is_vm_asleep
from agent.tools.errors import CommandError
from agent.vm_command import run_vm_command as _exec
from storage.service import email as email_service
from storage.service import email_account as email_account_service
from storage.service import pipeline_lock as pipeline_lock_service

router = APIRouter(prefix="/email")

# CloudFront's custom origin read timeout defaults to 30s and is not overridden.
# The route refuses a stopped VM before acquiring the lock (so ssh_exec never
# runs the unbounded ensure_and_touch_vm cold-boot prelude), then sizes the
# command timeout from the remaining budget. A representative per-account run of
# luohycs@gmail.com on 2026-08-25 completed in 10.33s.
_CLOUDFRONT_ORIGIN_TIMEOUT_SECONDS = 30.0
_SYNC_OVERHEAD_SECONDS = 4.0
_SYNC_TIMEOUT_SECONDS = _CLOUDFRONT_ORIGIN_TIMEOUT_SECONDS - _SYNC_OVERHEAD_SECONDS
_SYNC_LOCK_TTL_SECONDS = 60


def _get_user_id(request: Request) -> int:
    return request.state.user_id


def _sync_lock_action(user_id: int, address: str) -> str:
    return f"email-sync:{user_id}:{address}"


def _parse_sync_summary(output: str, address: str) -> dict:
    for line in reversed((output or "").splitlines()):
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("status") == "ok":
            count = int(candidate.get("count") or 0)
            return {
                "status": "ok",
                "address": candidate.get("address") or address,
                "count": count,
                "summary": f"Synced {count} new emails for {address}.",
            }
    raise HTTPException(status_code=502, detail="Email sync failed")


class EmailItem(BaseModel):
    external_id: Optional[str] = None
    subject: Optional[str] = None
    from_addr: str = ""
    to_addrs: Optional[List[str]] = None
    cc_addrs: Optional[List[str]] = None
    bcc_addrs: Optional[List[str]] = None
    date: int = 0
    content: Optional[str] = None
    thread_id: Optional[str] = None


class BatchCreateEmailsRequest(BaseModel):
    emails: List[EmailItem]
    account: Optional[str] = None


class AddEmailAccountRequest(BaseModel):
    address: str
    app_password: str


@router.get("/account/list")
async def list_email_accounts(request: Request):
    user_id = _get_user_id(request)
    accounts = email_account_service.list_accounts(user_id)
    return [a.to_dict() for a in accounts]


@router.get("/account/credentials")
async def list_email_account_credentials(request: Request):
    """Accounts with app passwords, for the owner's sync CLI only."""
    user_id = _get_user_id(request)
    accounts = email_account_service.list_accounts(user_id)
    return [a.to_dict(include_password=True) for a in accounts]


@router.post("/account")
async def add_email_account(req: AddEmailAccountRequest, request: Request):
    user_id = _get_user_id(request)
    address = req.address.strip()
    app_password = req.app_password.strip()
    if not address or not app_password:
        raise HTTPException(status_code=400, detail="address and app_password are required")
    account = email_account_service.add_account(user_id, address, app_password)
    return account.to_dict()


@router.delete("/account/{address}")
async def delete_email_account(address: str, request: Request):
    user_id = _get_user_id(request)
    if not email_account_service.delete_account(user_id, address):
        raise HTTPException(status_code=404, detail="Account not found")
    return {"ok": True, "address": address}


@router.post("/account/{address}/sync")
async def sync_email_account(address: str, request: Request):
    """Run host-owned `y email sync-gmail --account` for one registered account."""
    user_id = _get_user_id(request)
    address = address.strip()
    if not address or email_account_service.get_account(user_id, address) is None:
        raise HTTPException(status_code=404, detail="Account not found")

    vm_config = resolve_vm_config(user_id)
    if await asyncio.to_thread(is_vm_asleep, vm_config):
        raise HTTPException(
            status_code=503,
            detail="VM is stopped; retry after it is running",
        )

    lock_action = _sync_lock_action(user_id, address)
    if not pipeline_lock_service.try_acquire_exclusive_lock(
        lock_action, ttl_seconds=_SYNC_LOCK_TTL_SECONDS,
    ):
        raise HTTPException(status_code=409, detail="Sync already in progress")

    try:
        output = await _exec(
            user_id,
            ["y", "email", "sync-gmail", "--account", address, "--json"],
            timeout=_SYNC_TIMEOUT_SECONDS,
            check=True,
            wake=False,
        )
    except CommandError as exc:
        logger.warning("email sync failed address={} exit_code={}", address, exc.exit_code)
        if exc.exit_code == -1:
            raise HTTPException(status_code=504, detail="Email sync timed out") from None
        raise HTTPException(status_code=502, detail="Email sync failed") from None
    except Exception:
        logger.exception("email sync failed address={}", address)
        raise HTTPException(status_code=502, detail="Email sync failed") from None
    finally:
        pipeline_lock_service.release_lock(lock_action)

    return _parse_sync_summary(output, address)


@router.post("/batch")
async def batch_create_emails(req: BatchCreateEmailsRequest, request: Request):
    user_id = _get_user_id(request)
    count = email_service.add_emails_batch(
        user_id, [e.model_dump() for e in req.emails], account=req.account,
    )
    return {"count": count}


@router.get("/list")
async def list_emails(
    request: Request,
    query: Optional[str] = Query(None),
    account: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    on: Optional[str] = Query(None),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    created_on: Optional[str] = Query(None),
    created_from: Optional[str] = Query(None),
    created_to: Optional[str] = Query(None),
    updated_on: Optional[str] = Query(None),
    updated_from: Optional[str] = Query(None),
    updated_to: Optional[str] = Query(None),
):
    user_id = _get_user_id(request)
    emails = email_service.list_emails(
        user_id, query=query, account=account, tag=tag, limit=limit, offset=offset,
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    )
    return [e.to_dict() for e in emails]


@router.get("/threads")
async def list_threads(
    request: Request,
    query: Optional[str] = Query(None),
    account: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
    on: Optional[str] = Query(None),
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    created_on: Optional[str] = Query(None),
    created_from: Optional[str] = Query(None),
    created_to: Optional[str] = Query(None),
    updated_on: Optional[str] = Query(None),
    updated_from: Optional[str] = Query(None),
    updated_to: Optional[str] = Query(None),
):
    user_id = _get_user_id(request)
    emails = email_service.list_threads(
        user_id, query=query, account=account, limit=limit, offset=offset,
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    )
    return [e.to_dict() for e in emails]


@router.get("/thread/{thread_id}")
async def get_thread(thread_id: str, request: Request, account: Optional[str] = Query(None)):
    user_id = _get_user_id(request)
    emails = email_service.get_emails_by_thread(user_id, thread_id, account=account)
    return [e.to_dict() for e in emails]


@router.get("/{email_id}")
async def get_email(email_id: str, request: Request):
    user_id = _get_user_id(request)
    email = email_service.get_email(user_id, email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    return email.to_dict()
