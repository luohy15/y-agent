"""Function-based email repository using SQLAlchemy sessions."""

from typing import List, Optional
from sqlalchemy import func
from storage.entity.email import EmailEntity
from storage.entity.entity_tag import EntityTagEntity
from storage.entity.tag_vocabulary import TagVocabularyEntity
from storage.dto.email import Email
from storage.database.base import get_db
from storage.util import apply_time_filter, generate_id


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
        account=entity.account,
        created_at=entity.created_at if entity.created_at else None,
        updated_at=entity.updated_at if entity.updated_at else None,
        created_at_unix=entity.created_at_unix if entity.created_at_unix else None,
        updated_at_unix=entity.updated_at_unix if entity.updated_at_unix else None,
    )


def save_emails_batch(user_id: int, emails: List[dict], account: Optional[str] = None) -> int:
    """Batch insert emails with dedup on (account, external_id). Returns count of emails created."""
    if not emails:
        return 0

    with get_db() as session:
        external_ids = [e['external_id'] for e in emails if e.get('external_id')]
        existing_ids = set()
        if external_ids:
            existing = session.query(EmailEntity.external_id).filter(
                EmailEntity.user_id == user_id,
                EmailEntity.account == account,
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
                account=account,
            )
            session.add(entity)
            count += 1

    return count


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
    with get_db() as session:
        q = session.query(EmailEntity).filter(EmailEntity.user_id == user_id)
        if account:
            q = q.filter(EmailEntity.account == account)
        if query:
            pattern = f"%{query}%"
            q = q.filter(
                (EmailEntity.subject.like(pattern))
                | (EmailEntity.from_addr.like(pattern))
                | (EmailEntity.content.like(pattern))
            )
        if tag is not None:
            tagged_thread_ids = session.query(EntityTagEntity.entity_id).filter_by(
                user_id=user_id, entity_type="email", tag=tag,
            )
            q = q.filter(func.coalesce(EmailEntity.thread_id, EmailEntity.email_id).in_(tagged_thread_ids))
        q = apply_time_filter(q, EmailEntity.date, on=on, from_=from_, to=to, field_type="unix_ms")
        q = apply_time_filter(q, EmailEntity.created_at, on=created_on, from_=created_from, to=created_to)
        q = apply_time_filter(q, EmailEntity.updated_at, on=updated_on, from_=updated_from, to=updated_to)
        q = q.order_by(EmailEntity.date.desc())
        q = q.offset(offset).limit(limit)
        return [_row_to_dto(e) for e in q.all()]


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
    """Group emails into threads (key = COALESCE(thread_id, email_id)).

    Returns one representative Email per thread (the latest message, Gmail-style),
    carrying ``thread_count`` and the group key as ``thread_id``. Threads are
    ordered by latest activity (MAX(date)) descending and paginated on the grouped
    result so a thread straddling a page boundary still collapses to a single row.
    """
    with get_db() as session:
        thread_key = func.coalesce(EmailEntity.thread_id, EmailEntity.email_id)
        base = session.query(EmailEntity).filter(EmailEntity.user_id == user_id)
        if tag is not None:
            tagged_thread_ids = session.query(EntityTagEntity.entity_id).filter_by(
                user_id=user_id, entity_type="email", tag=tag,
            )
            base = base.filter(thread_key.in_(tagged_thread_ids))
        if account:
            base = base.filter(EmailEntity.account == account)
        if query:
            pattern = f"%{query}%"
            base = base.filter(
                (EmailEntity.subject.like(pattern))
                | (EmailEntity.from_addr.like(pattern))
                | (EmailEntity.content.like(pattern))
            )
        base = apply_time_filter(base, EmailEntity.date, on=on, from_=from_, to=to, field_type="unix_ms")
        base = apply_time_filter(base, EmailEntity.created_at, on=created_on, from_=created_from, to=created_to)
        base = apply_time_filter(base, EmailEntity.updated_at, on=updated_on, from_=updated_from, to=updated_to)

        grouped = (
            base.with_entities(
                thread_key.label("tkey"),
                func.count().label("cnt"),
                func.max(EmailEntity.date).label("maxdate"),
            )
            .group_by(thread_key)
            .order_by(func.max(EmailEntity.date).desc())
            .offset(offset)
            .limit(limit)
        )
        rows = grouped.all()
        if not rows:
            return []

        keys = [r.tkey for r in rows]
        counts = {r.tkey: r.cnt for r in rows}
        maxdates = {r.tkey: r.maxdate for r in rows}

        # Load the representative (latest) message per thread on this page.
        candidates = base.filter(thread_key.in_(keys)).all()
        rep_by_key = {}
        for e in candidates:
            k = e.thread_id or e.email_id
            if e.date == maxdates.get(k) and k not in rep_by_key:
                rep_by_key[k] = e

        result = []
        for k in keys:
            e = rep_by_key.get(k)
            if e is None:
                continue
            dto = _row_to_dto(e)
            dto.thread_id = k
            dto.thread_count = counts[k]
            result.append(dto)
        tags_by_thread = list_thread_tags_by_ids(user_id, keys)
        for dto in result:
            dto.tags = tags_by_thread.get(dto.thread_id or dto.email_id, [])
        return result


def get_email(user_id: int, email_id: str) -> Optional[Email]:
    with get_db() as session:
        entity = session.query(EmailEntity).filter_by(
            user_id=user_id, email_id=email_id,
        ).first()
        if not entity:
            return None
        return _row_to_dto(entity)


def get_thread_representatives(user_id: int, thread_ids: List[str]) -> List[Email]:
    """Return the latest message for each owner-scoped canonical thread key."""
    if not thread_ids:
        return []
    with get_db() as session:
        thread_key = func.coalesce(EmailEntity.thread_id, EmailEntity.email_id)
        rows = (
            session.query(EmailEntity)
            .filter(EmailEntity.user_id == user_id, thread_key.in_(thread_ids))
            .order_by(EmailEntity.date.desc())
            .all()
        )
        representatives = {}
        for row in rows:
            key = row.thread_id or row.email_id
            representatives.setdefault(key, row)
        return [_row_to_dto(row) for row in representatives.values()]


def thread_exists(user_id: int, thread_id: str) -> bool:
    """Return whether an owner has an email with this canonical thread key."""
    with get_db() as session:
        thread_key = func.coalesce(EmailEntity.thread_id, EmailEntity.email_id)
        return session.query(EmailEntity.id).filter(
            EmailEntity.user_id == user_id,
            thread_key == thread_id,
        ).first() is not None


def list_thread_tags(user_id: int, thread_id: str) -> List[str]:
    return list_thread_tags_by_ids(user_id, [thread_id]).get(thread_id, [])


def list_thread_tags_by_ids(user_id: int, thread_ids: List[str]) -> dict[str, List[str]]:
    if not thread_ids:
        return {}
    with get_db() as session:
        rows = session.query(EntityTagEntity.entity_id, EntityTagEntity.tag).filter(
            EntityTagEntity.user_id == user_id,
            EntityTagEntity.entity_type == "email",
            EntityTagEntity.entity_id.in_(thread_ids),
        ).order_by(EntityTagEntity.entity_id, EntityTagEntity.tag).all()
        result = {thread_id: [] for thread_id in thread_ids}
        for row in rows:
            result[row.entity_id].append(row.tag)
        return result


def vocabulary_contains(user_id: int, tag: str) -> bool:
    with get_db() as session:
        return session.query(TagVocabularyEntity.id).filter_by(
            user_id=user_id, tag=tag,
        ).first() is not None


def add_thread_tag(user_id: int, thread_id: str, tag: str) -> bool:
    with get_db() as session:
        exists = session.query(EntityTagEntity.id).filter_by(
            user_id=user_id, entity_type="email", entity_id=thread_id, tag=tag,
        ).first()
        if exists:
            return False
        session.add(EntityTagEntity(
            user_id=user_id, entity_type="email", entity_id=thread_id, tag=tag,
        ))
        return True


def remove_thread_tag(user_id: int, thread_id: str, tag: str) -> bool:
    with get_db() as session:
        row = session.query(EntityTagEntity).filter_by(
            user_id=user_id, entity_type="email", entity_id=thread_id, tag=tag,
        ).first()
        if not row:
            return False
        session.delete(row)
        return True


def get_emails_by_thread(user_id: int, thread_id: str, account: Optional[str] = None) -> List[Email]:
    """Return all emails of a thread, oldest->newest.

    Matches ``thread_id == key`` or, for a singleton email with no thread_id, the
    null-thread fallback ``email_id == key`` (the group key used by list_threads).
    """
    with get_db() as session:
        q = session.query(EmailEntity).filter(
            EmailEntity.user_id == user_id,
        )
        if account:
            q = q.filter(EmailEntity.account == account)
        q = q.filter(
            (EmailEntity.thread_id == thread_id)
            | ((EmailEntity.thread_id.is_(None)) & (EmailEntity.email_id == thread_id))
        ).order_by(EmailEntity.date.asc())
        return [_row_to_dto(e) for e in q.all()]
