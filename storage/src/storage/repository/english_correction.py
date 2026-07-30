"""Function-based english_correction repository using SQLAlchemy sessions."""

from typing import List, Optional, Set, Tuple

from sqlalchemy import cast, String

from storage.database.base import get_db
from storage.dto.english_correction import EnglishCorrection
from storage.entity.english_correction import EnglishCorrectionEntity
from storage.util import apply_time_filter


def _entity_to_dto(entity: EnglishCorrectionEntity) -> EnglishCorrection:
    cats = entity.error_categories or []
    if not isinstance(cats, list):
        cats = list(cats)
    return EnglishCorrection(
        correction_id=entity.correction_id,
        chat_id=entity.chat_id,
        message_id=entity.message_id,
        message_at=entity.message_at,
        message_at_unix=int(entity.message_at_unix),
        original_text=entity.original_text,
        corrected_text=entity.corrected_text,
        error_categories=[str(c) for c in cats],
        explanation=entity.explanation,
        dismissed=bool(entity.dismissed),
        created_at=entity.created_at if entity.created_at else None,
        updated_at=entity.updated_at if entity.updated_at else None,
        created_at_unix=entity.created_at_unix if entity.created_at_unix else None,
        updated_at_unix=entity.updated_at_unix if entity.updated_at_unix else None,
    )


def list_corrections(
    user_id: int,
    dismissed: Optional[bool] = None,
    category: Optional[str] = None,
    query: Optional[str] = None,
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
) -> List[EnglishCorrection]:
    with get_db() as session:
        q = session.query(EnglishCorrectionEntity).filter_by(user_id=user_id)
        if dismissed is not None:
            q = q.filter_by(dismissed=dismissed)
        if category:
            # Free-form categories are a JSON array of strings. Cast to text and
            # match a quoted token so we stay portable across SQLite tests and
            # Postgres (JSONB maps to SQLAlchemy JSON).
            needle = f'"{category}"'
            q = q.filter(cast(EnglishCorrectionEntity.error_categories, String).like(f"%{needle}%"))
        if query:
            like = f"%{query}%"
            q = q.filter(
                (EnglishCorrectionEntity.original_text.ilike(like))
                | (EnglishCorrectionEntity.corrected_text.ilike(like))
                | (EnglishCorrectionEntity.explanation.ilike(like))
            )
        # Canonical time field for list: created_at
        q = apply_time_filter(q, EnglishCorrectionEntity.created_at, on=on, from_=from_, to=to)
        q = apply_time_filter(
            q, EnglishCorrectionEntity.created_at,
            on=created_on, from_=created_from, to=created_to,
        )
        q = apply_time_filter(
            q, EnglishCorrectionEntity.updated_at,
            on=updated_on, from_=updated_from, to=updated_to,
        )
        rows = (
            q.order_by(EnglishCorrectionEntity.message_at_unix.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [_entity_to_dto(r) for r in rows]


def get_correction(user_id: int, correction_id: str) -> Optional[EnglishCorrection]:
    with get_db() as session:
        row = (
            session.query(EnglishCorrectionEntity)
            .filter_by(user_id=user_id, correction_id=correction_id)
            .first()
        )
        return _entity_to_dto(row) if row else None


def find_by_message(
    user_id: int, chat_id: str, message_id: str
) -> Optional[EnglishCorrection]:
    with get_db() as session:
        row = (
            session.query(EnglishCorrectionEntity)
            .filter_by(user_id=user_id, chat_id=chat_id, message_id=message_id)
            .first()
        )
        return _entity_to_dto(row) if row else None


def list_message_keys(
    user_id: int, since_unix: Optional[int] = None
) -> Set[Tuple[str, str]]:
    """Return the (chat_id, message_id) pairs already corrected in the window.

    Used by the pending scan to dedup a whole batch with one query instead of a
    `find_by_message` per candidate.
    """
    with get_db() as session:
        q = session.query(
            EnglishCorrectionEntity.chat_id, EnglishCorrectionEntity.message_id
        ).filter_by(user_id=user_id)
        if since_unix is not None:
            q = q.filter(EnglishCorrectionEntity.message_at_unix >= since_unix)
        return {(row[0], row[1]) for row in q}


def save_correction(user_id: int, correction: EnglishCorrection) -> EnglishCorrection:
    with get_db() as session:
        entity = (
            session.query(EnglishCorrectionEntity)
            .filter_by(user_id=user_id, correction_id=correction.correction_id)
            .first()
        )
        fields = dict(
            chat_id=correction.chat_id,
            message_id=correction.message_id,
            message_at=correction.message_at,
            message_at_unix=correction.message_at_unix,
            original_text=correction.original_text,
            corrected_text=correction.corrected_text,
            error_categories=list(correction.error_categories or []),
            explanation=correction.explanation,
            dismissed=bool(correction.dismissed),
        )
        if entity:
            for k, v in fields.items():
                setattr(entity, k, v)
        else:
            entity = EnglishCorrectionEntity(
                user_id=user_id,
                correction_id=correction.correction_id,
                **fields,
            )
            session.add(entity)
        session.flush()
        return _entity_to_dto(entity)
