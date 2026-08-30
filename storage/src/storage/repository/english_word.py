"""Function-based english_word repository using SQLAlchemy sessions."""

from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, or_

from storage.database.base import get_db
from storage.dto.english_word import EnglishWord
from storage.entity.english_word import EnglishWordEntity
from storage.util import apply_time_filter, generate_id, get_unix_timestamp, get_utc_iso8601_timestamp


VALID_STATUSES = ("unseen", "known", "unknown")
TIER_BANDS: Tuple[Tuple[str, int], ...] = (("3k", 3000), ("5k", 5000), ("10k", 10000))


def _entity_to_dto(entity: EnglishWordEntity) -> EnglishWord:
    marked_unix = entity.marked_at_unix
    return EnglishWord(
        word_id=entity.word_id,
        word=entity.word,
        rank=int(entity.rank),
        status=entity.status,
        marked_at=entity.marked_at,
        marked_at_unix=int(marked_unix) if marked_unix is not None else None,
        created_at=entity.created_at if entity.created_at else None,
        updated_at=entity.updated_at if entity.updated_at else None,
        created_at_unix=entity.created_at_unix if entity.created_at_unix else None,
        updated_at_unix=entity.updated_at_unix if entity.updated_at_unix else None,
    )


def list_words(
    user_id: int,
    status: Optional[str] = None,
    max_rank: Optional[int] = None,
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
) -> List[EnglishWord]:
    with get_db() as session:
        q = session.query(EnglishWordEntity).filter_by(user_id=user_id)
        if status:
            q = q.filter_by(status=status)
        if max_rank is not None:
            q = q.filter(EnglishWordEntity.rank <= int(max_rank))
        # Canonical time field for list: marked_at
        q = apply_time_filter(q, EnglishWordEntity.marked_at, on=on, from_=from_, to=to)
        q = apply_time_filter(
            q, EnglishWordEntity.created_at,
            on=created_on, from_=created_from, to=created_to,
        )
        q = apply_time_filter(
            q, EnglishWordEntity.updated_at,
            on=updated_on, from_=updated_from, to=updated_to,
        )
        rows = (
            q.order_by(EnglishWordEntity.rank.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [_entity_to_dto(r) for r in rows]


def seed_words(user_id: int, ranked: Sequence[Tuple[int, str]]) -> Dict[str, int]:
    """Insert missing words and refresh ranks. Never touches status/marked_at."""
    with get_db() as session:
        existing_rows = (
            session.query(EnglishWordEntity)
            .filter_by(user_id=user_id)
            .all()
        )
        by_word = {row.word: row for row in existing_rows}
        used_ids = {row.word_id for row in existing_rows}
        inserted = 0
        updated = 0
        for rank, word in ranked:
            row = by_word.get(word)
            if row is None:
                word_id = generate_id()
                while word_id in used_ids:
                    word_id = generate_id()
                used_ids.add(word_id)
                entity = EnglishWordEntity(
                    user_id=user_id,
                    word_id=word_id,
                    word=word,
                    rank=int(rank),
                    status="unseen",
                )
                session.add(entity)
                by_word[word] = entity
                inserted += 1
            elif int(row.rank) != int(rank):
                row.rank = int(rank)
                updated += 1
        session.flush()
        total = session.query(func.count(EnglishWordEntity.id)).filter_by(user_id=user_id).scalar() or 0
        return {"inserted": inserted, "updated": updated, "total": int(total)}


def mark_words(
    user_id: int,
    status: str,
    word_ids: Optional[Sequence[str]] = None,
    words: Optional[Sequence[str]] = None,
) -> List[EnglishWord]:
    ids = [w for w in (word_ids or []) if w]
    word_values = [w.lower() for w in (words or []) if w]
    if not ids and not word_values:
        return []
    now = get_utc_iso8601_timestamp()
    now_unix = get_unix_timestamp()
    with get_db() as session:
        q = session.query(EnglishWordEntity).filter_by(user_id=user_id)
        conds = []
        if ids:
            conds.append(EnglishWordEntity.word_id.in_(ids))
        if word_values:
            conds.append(EnglishWordEntity.word.in_(word_values))
        q = q.filter(or_(*conds))
        rows = q.all()
        for row in rows:
            row.status = status
            row.marked_at = now
            row.marked_at_unix = now_unix
        session.flush()
        return [_entity_to_dto(r) for r in rows]


def stats(user_id: int) -> Dict:
    with get_db() as session:
        rows = (
            session.query(EnglishWordEntity.status, EnglishWordEntity.rank)
            .filter_by(user_id=user_id)
            .all()
        )
        next_unseen = (
            session.query(func.min(EnglishWordEntity.rank))
            .filter_by(user_id=user_id, status="unseen")
            .scalar()
        )

    tiers = []
    for label, max_rank in TIER_BANDS:
        known = unknown = total = 0
        for status, rank in rows:
            if int(rank) > max_rank:
                continue
            total += 1
            if status == "known":
                known += 1
            elif status == "unknown":
                unknown += 1
        reviewed = known + unknown
        percent = round((reviewed / total) * 100) if total else 0
        tiers.append({
            "label": label,
            "max_rank": max_rank,
            "total": total,
            "known": known,
            "unknown": unknown,
            "reviewed": reviewed,
            "percent": percent,
        })

    overall_known = sum(1 for status, _ in rows if status == "known")
    overall_unknown = sum(1 for status, _ in rows if status == "unknown")
    reviewed = overall_known + overall_unknown
    return {
        "tiers": tiers,
        "reviewed": reviewed,
        "total": len(rows),
        "next_unseen_rank": int(next_unseen) if next_unseen is not None else None,
    }
