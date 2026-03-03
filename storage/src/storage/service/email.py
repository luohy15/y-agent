"""Email service."""

from typing import List, Optional
from storage.dto.email import Email
from storage.repository import email as email_repo


def add_emails_batch(user_id: int, emails: List[dict]) -> int:
    """Batch add emails from dicts. Returns count."""
    return email_repo.save_emails_batch(user_id, emails)


def list_emails(
    user_id: int,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Email]:
    return email_repo.list_emails(user_id, query=query, limit=limit, offset=offset)


def get_email(user_id: int, email_id: str) -> Optional[Email]:
    return email_repo.get_email(user_id, email_id)


def get_emails_by_thread(user_id: int, thread_id: str) -> List[Email]:
    return email_repo.get_emails_by_thread(user_id, thread_id)
