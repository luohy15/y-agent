"""Email service."""

from typing import List, Optional
from storage.dto.email import Email
from storage.repository import email as email_repo
from storage.service import tag as tag_service


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
    tag: Optional[str] = None,
) -> List[Email]:
    return email_repo.list_emails(
        user_id, query=query, account=account, limit=limit, offset=offset,
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
        tag=tag,
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
    tag: Optional[str] = None,
) -> List[Email]:
    return email_repo.list_threads(
        user_id, query=query, account=account, limit=limit, offset=offset,
        on=on, from_=from_, to=to,
        created_on=created_on, created_from=created_from, created_to=created_to,
        updated_on=updated_on, updated_from=updated_from, updated_to=updated_to,
        tag=tag,
    )


def get_email(user_id: int, email_id: str) -> Optional[Email]:
    return email_repo.get_email(user_id, email_id)


def get_emails_by_thread(user_id: int, thread_id: str, account: Optional[str] = None) -> List[Email]:
    return email_repo.get_emails_by_thread(user_id, thread_id, account=account)


class EmailTagError(ValueError):
    """Email thread tag mutation failed validation."""


def _canonical_vocabulary_tag(tag: str) -> str:
    canonical = tag_service.normalize_tag(tag)
    if not canonical or canonical != tag:
        raise EmailTagError("tag must be a canonical vocabulary value")
    return canonical


def _require_thread(user_id: int, thread_id: str) -> None:
    if not thread_id or not email_repo.thread_exists(user_id, thread_id):
        raise LookupError("Email thread not found")


def list_thread_tags(user_id: int, thread_id: str) -> List[str]:
    _require_thread(user_id, thread_id)
    return email_repo.list_thread_tags(user_id, thread_id)


def add_thread_tag(user_id: int, thread_id: str, tag: str) -> bool:
    _require_thread(user_id, thread_id)
    canonical = _canonical_vocabulary_tag(tag)
    if not email_repo.vocabulary_contains(user_id, canonical):
        raise LookupError("Tag is not in the vocabulary")
    return email_repo.add_thread_tag(user_id, thread_id, canonical)


def remove_thread_tag(user_id: int, thread_id: str, tag: str) -> bool:
    _require_thread(user_id, thread_id)
    canonical = _canonical_vocabulary_tag(tag)
    return email_repo.remove_thread_tag(user_id, thread_id, canonical)


def add_tag(user_id: int, entity_id: str, tag: str) -> bool:
    """Generic email tag write routed through the canonical thread contract."""
    return add_thread_tag(user_id, entity_id, tag)


def remove_tag(user_id: int, entity_id: str, tag: str) -> bool:
    """Generic email tag removal routed through the canonical thread contract."""
    return remove_thread_tag(user_id, entity_id, tag)


def _resolve_tagged_emails(user_id: int, thread_ids: List[str]) -> dict:
    return {
        email.thread_id or email.email_id: {
            "id": email.thread_id or email.email_id,
            "title": email.subject or email.from_addr,
        }
        for email in email_repo.get_thread_representatives(user_id, thread_ids)
    }


tag_service.register_resolver("email", _resolve_tagged_emails)
