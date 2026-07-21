from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import email as email_service
from storage.service import email_account as email_account_service

router = APIRouter(prefix="/email")


def _get_user_id(request: Request) -> int:
    return request.state.user_id


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
