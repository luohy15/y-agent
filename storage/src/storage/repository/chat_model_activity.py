"""Repository for derived per-chat, per-day model activity."""

from datetime import date

from sqlalchemy import delete, func, insert, select

from storage.database.base import get_db
from storage.entity.chat import ChatEntity
from storage.entity.chat_model_activity import ChatModelActivityEntity


def _replace_for_chat(
    session,
    user_id: int,
    chat_id: str,
    rows: list[dict],
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> int:
    delete_stmt = delete(ChatModelActivityEntity).where(
        ChatModelActivityEntity.user_id == user_id,
        ChatModelActivityEntity.chat_id == chat_id,
    )
    if from_date is not None:
        delete_stmt = delete_stmt.where(ChatModelActivityEntity.usage_date >= from_date)
    if to_date is not None:
        delete_stmt = delete_stmt.where(ChatModelActivityEntity.usage_date <= to_date)
    session.execute(delete_stmt)
    if rows:
        session.execute(insert(ChatModelActivityEntity), [
            {
                "user_id": user_id,
                "chat_id": chat_id,
                "usage_date": row["usage_date"],
                "model": row["model"],
                "turns": int(row.get("turns") or 0),
            }
            for row in rows
        ])
    return len(rows)


def recompute_for_chat(
    user_id: int,
    chat_id: str,
    rows: list[dict],
    *,
    from_date: date | None = None,
    to_date: date | None = None,
) -> int:
    """Replace one chat's derived facts, wholly or within an inclusive range."""
    with get_db() as session:
        return _replace_for_chat(
            session,
            user_id,
            chat_id,
            rows,
            from_date=from_date,
            to_date=to_date,
        )


def recompute_updated_chats(
    user_id: int,
    since_unix: int,
    through_unix: int,
    derive_rows,
) -> dict:
    """Recompute one bounded revision window atomically with its watermark."""
    from storage.entity.user_preference import UserPreferenceEntity
    from storage.service.chat_model_activity import WATERMARK_KEY

    with get_db() as session:
        rows = session.execute(
            select(
                ChatEntity.chat_id,
                ChatEntity.json_content,
                ChatEntity.updated_at_unix,
            )
            .where(
                ChatEntity.user_id == user_id,
                ChatEntity.updated_at_unix >= since_unix,
                ChatEntity.updated_at_unix <= through_unix,
            )
            .order_by(ChatEntity.updated_at_unix.asc(), ChatEntity.id.asc())
        ).all()
        activity_rows = 0
        for row in rows:
            activity_rows += _replace_for_chat(
                session,
                user_id,
                row.chat_id,
                derive_rows(row.json_content),
            )

        deleted = session.execute(
            delete(ChatModelActivityEntity).where(
                ChatModelActivityEntity.user_id == user_id,
                ~ChatModelActivityEntity.chat_id.in_(
                    select(ChatEntity.chat_id).where(ChatEntity.user_id == user_id)
                ),
            )
        ).rowcount or 0

        preference = session.execute(
            select(UserPreferenceEntity)
            .where(
                UserPreferenceEntity.user_id == user_id,
                UserPreferenceEntity.key == WATERMARK_KEY,
            )
            .with_for_update()
        ).scalar_one_or_none()
        current_watermark = 0
        if preference is not None and isinstance(preference.value, dict):
            current_watermark = int(preference.value.get("updated_at_unix") or 0)
        next_watermark = max(current_watermark, through_unix)
        if preference is None:
            session.add(UserPreferenceEntity(
                user_id=user_id,
                key=WATERMARK_KEY,
                value={"updated_at_unix": next_watermark},
            ))
        else:
            preference.value = {"updated_at_unix": next_watermark}
        return {
            "chats": len(rows),
            "rows": activity_rows,
            "deleted": int(deleted),
        }


def list_chat_batch(
    user_id: int,
    after_id: int = 0,
    batch_size: int = 100,
) -> list[tuple[int, str, str]]:
    """Return one keyset page of chat bodies for historical backfill."""
    with get_db() as session:
        rows = (
            session.query(ChatEntity.id, ChatEntity.chat_id, ChatEntity.json_content)
            .filter(ChatEntity.user_id == user_id, ChatEntity.id > after_id)
            .order_by(ChatEntity.id.asc())
            .limit(batch_size)
            .all()
        )
        return [(row.id, row.chat_id, row.json_content) for row in rows]


def sweep_orphans(user_id: int) -> int:
    """Delete activity whose chat no longer exists for this owner."""
    with get_db() as session:
        live_chat_ids = session.query(ChatEntity.chat_id).filter(
            ChatEntity.user_id == user_id,
        )
        deleted = (
            session.query(ChatModelActivityEntity)
            .filter(ChatModelActivityEntity.user_id == user_id)
            .filter(~ChatModelActivityEntity.chat_id.in_(live_chat_ids))
            .delete(synchronize_session=False)
        )
        return int(deleted or 0)


def aggregate(
    user_id: int,
    from_date: date | None,
    to_date: date | None,
) -> dict:
    """Aggregate model rows and distinct chats for an optionally bounded window."""
    with get_db() as session:
        base = session.query(ChatModelActivityEntity).filter(
            ChatModelActivityEntity.user_id == user_id,
        )
        if from_date is not None:
            base = base.filter(ChatModelActivityEntity.usage_date >= from_date)
        if to_date is not None:
            base = base.filter(ChatModelActivityEntity.usage_date <= to_date)
        model_rows = (
            base.with_entities(
                ChatModelActivityEntity.model,
                func.count(func.distinct(ChatModelActivityEntity.chat_id)).label("sessions"),
                func.coalesce(func.sum(ChatModelActivityEntity.turns), 0).label("turns"),
            )
            .group_by(ChatModelActivityEntity.model)
            .order_by(ChatModelActivityEntity.model.asc())
            .all()
        )
        total = base.with_entities(
            func.count(func.distinct(ChatModelActivityEntity.chat_id)).label("sessions"),
            func.coalesce(func.sum(ChatModelActivityEntity.turns), 0).label("turns"),
        ).one()
        return {
            "models": [
                {"model": row.model, "sessions": int(row.sessions), "turns": int(row.turns)}
                for row in model_rows
            ],
            "total": {"sessions": int(total.sessions), "turns": int(total.turns)},
        }
