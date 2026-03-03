"""Function-based email repository using SQLAlchemy sessions."""

from typing import List, Optional
from storage.entity.email import EmailEntity
from storage.dto.email import Email
from storage.database.base import get_db
from storage.util import generate_id


def _row_to_dto(entity: EmailEntity) -> Email:
    return Email(
        email_id=entity.email_id,
        subject=entity.subject,
        from_addr=entity.from_addr,
        to_addrs=entity.to_addrs,
        cc_addrs=entity.cc_addrs,
        bcc_addrs=entity.bcc_addrs,
        date=entity.date,
        content=entity.content,
        thread_id=entity.thread_id,
        created_at=entity.created_at if entity.created_at else None,
        updated_at=entity.updated_at if entity.updated_at else None,
        created_at_unix=entity.created_at_unix if entity.created_at_unix else None,
        updated_at_unix=entity.updated_at_unix if entity.updated_at_unix else None,
    )


def save_emails_batch(user_id: int, emails: List[dict]) -> int:
    """Batch insert emails with dedup on external_id. Returns count of emails created."""
    if not emails:
        return 0

    with get_db() as session:
        external_ids = [e['external_id'] for e in emails if e.get('external_id')]
        existing_ids = set()
        if external_ids:
            existing = session.query(EmailEntity.external_id).filter(
                EmailEntity.user_id == user_id,
                EmailEntity.external_id.in_(external_ids),
            ).all()
            existing_ids = {row.external_id for row in existing}

        count = 0
        for item in emails:
            ext_id = item.get('external_id')
            if ext_id and ext_id in existing_ids:
                continue
            entity = EmailEntity(
                user_id=user_id,
                email_id=generate_id(),
                external_id=ext_id,
                subject=item.get('subject'),
                from_addr=item.get('from_addr', ''),
                to_addrs=item.get('to_addrs', []),
                cc_addrs=item.get('cc_addrs'),
                bcc_addrs=item.get('bcc_addrs'),
                date=item.get('date', 0),
                content=item.get('content'),
                thread_id=item.get('thread_id'),
            )
            session.add(entity)
            count += 1

    return count


def list_emails(
    user_id: int,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Email]:
    with get_db() as session:
        q = session.query(EmailEntity).filter(EmailEntity.user_id == user_id)
        if query:
            pattern = f"%{query}%"
            q = q.filter(
                (EmailEntity.subject.like(pattern))
                | (EmailEntity.from_addr.like(pattern))
                | (EmailEntity.content.like(pattern))
            )
        q = q.order_by(EmailEntity.date.desc())
        q = q.offset(offset).limit(limit)
        return [_row_to_dto(e) for e in q.all()]


def get_email(user_id: int, email_id: str) -> Optional[Email]:
    with get_db() as session:
        entity = session.query(EmailEntity).filter_by(
            user_id=user_id, email_id=email_id,
        ).first()
        if not entity:
            return None
        return _row_to_dto(entity)


def get_emails_by_thread(user_id: int, thread_id: str) -> List[Email]:
    with get_db() as session:
        q = session.query(EmailEntity).filter_by(
            user_id=user_id, thread_id=thread_id,
        ).order_by(EmailEntity.date.asc())
        return [_row_to_dto(e) for e in q.all()]
