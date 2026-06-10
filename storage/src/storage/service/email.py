"""Email service."""

from typing import List, Optional
from storage.dto.email import Email
from storage.repository import email as email_repo


def add_emails_batch(user_id: int, emails: List[dict], account: Optional[str] = None) -> int:
    """Batch add emails from dicts. Returns count."""
    return email_repo.save_emails_batch(user_id, emails, account=account)


def list_emails(
    user_id: int,
    query: Optional[str] = None,
    account: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    on: Optional[str] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
    created_on: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_on: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
) -> List[Email]:
    return email_repo.list_emails(
        user_id, query=query, account=account, limit=limit, offset=offset,
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    )


def list_threads(
    user_id: int,
    query: Optional[str] = None,
    account: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    on: Optional[str] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
    created_on: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_on: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
) -> List[Email]:
    return email_repo.list_threads(
        user_id, query=query, account=account, limit=limit, offset=offset,
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
    )


def get_email(user_id: int, email_id: str) -> Optional[Email]:
    return email_repo.get_email(user_id, email_id)


def get_emails_by_thread(user_id: int, thread_id: str, account: Optional[str] = None) -> List[Email]:
    return email_repo.get_emails_by_thread(user_id, thread_id, account=account)
