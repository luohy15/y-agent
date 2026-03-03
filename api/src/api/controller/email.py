from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from storage.service import email as email_service

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


@router.post("/batch")
async def batch_create_emails(req: BatchCreateEmailsRequest, request: Request):
    user_id = _get_user_id(request)
    count = email_service.add_emails_batch(
        user_id, [e.model_dump() for e in req.emails],
    )
    return {"count": count}


@router.get("/list")
async def list_emails(
    request: Request,
    query: Optional[str] = Query(None),
    limit: int = Query(50),
    offset: int = Query(0),
):
    user_id = _get_user_id(request)
    emails = email_service.list_emails(user_id, query=query, limit=limit, offset=offset)
    return [e.to_dict() for e in emails]


@router.get("/thread/{thread_id}")
async def get_thread(thread_id: str, request: Request):
    user_id = _get_user_id(request)
    emails = email_service.get_emails_by_thread(user_id, thread_id)
    return [e.to_dict() for e in emails]


@router.get("/{email_id}")
async def get_email(email_id: str, request: Request):
    user_id = _get_user_id(request)
    email = email_service.get_email(user_id, email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    return email.to_dict()
