"""Repository for session context analysis rows (todo 3844).

A unit is one (owner, chat, transcript session). Replacing a unit runs in one
transaction under a per-unit advisory lock: the stored analyzer version is
read FOR UPDATE, the unit's detail rows are deleted and the new ones inserted.
Expired detail (units analysed before the cutoff) is purged in the same
transaction; the unit's session row stays.
"""

from sqlalchemy import case, delete, exists, func, select, text, tuple_
from sqlalchemy.exc import IntegrityError

from storage.database.base import get_db
from storage.entity.chat_context import (
    ChatContextContributorEntity,
    ChatContextRequestEntity,
    ChatContextSessionEntity,
)
from storage.entity.chat_request_usage import ChatRequestUsageEntity


Session = ChatContextSessionEntity
Request = ChatContextRequestEntity
Contributor = ChatContextContributorEntity


def _lock_unit(session, user_id: int, chat_id: str, session_id: str) -> None:
    """Serialize writers of one unit until commit. SQLite has one writer anyway."""
    if session.get_bind().dialect.name != "postgresql":
        return
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"chat_context|{user_id}|{chat_id}|{session_id}"},
    )


def _purge_expired(session, user_id: int, cutoff_unix: int) -> None:
    expired = select(Session.chat_id, Session.session_id).where(
        Session.user_id == user_id,
        Session.analyzed_at_unix < cutoff_unix,
    )
    for entity in (Request, Contributor):
        session.execute(
            delete(entity)
            .where(
                entity.user_id == user_id,
                tuple_(entity.chat_id, entity.session_id).in_(expired),
            )
            .execution_options(synchronize_session=False)
        )


def replace_unit(user_id: int, unit: dict, requests: list[dict], contributors: list[dict],
                 cutoff_unix: int) -> str:
    """Replace one unit. Returns `replaced`, `stale_analyzer_version` or `request_conflict`.

    Nothing is written unless the result is `replaced`.
    """
    chat_id, session_id = unit["chat_id"], unit["session_id"]
    try:
        with get_db() as session:
            _lock_unit(session, user_id, chat_id, session_id)
            stored = session.execute(
                select(Session)
                .where(Session.user_id == user_id, Session.chat_id == chat_id,
                       Session.session_id == session_id)
                .with_for_update()
            ).scalar_one_or_none()
            if stored is not None and stored.analyzer_version > unit["analyzer_version"]:
                return "stale_analyzer_version"
            request_ids = [row["request_id"] for row in requests]
            if request_ids:
                elsewhere = session.execute(
                    select(Request.request_id).where(
                        Request.user_id == user_id,
                        Request.request_id.in_(request_ids),
                        ~((Request.chat_id == chat_id) & (Request.session_id == session_id)),
                    ).limit(1)
                ).first()
                if elsewhere is not None:
                    session.rollback()
                    return "request_conflict"

            _purge_expired(session, user_id, cutoff_unix)
            for entity in (Request, Contributor):
                session.execute(
                    delete(entity)
                    .where(entity.user_id == user_id, entity.chat_id == chat_id,
                           entity.session_id == session_id)
                    .execution_options(synchronize_session=False)
                )
            if stored is None:
                stored = Session(user_id=user_id, chat_id=chat_id, session_id=session_id)
                session.add(stored)
            for key, value in unit.items():
                setattr(stored, key, value)
            session.add_all(
                Request(user_id=user_id, chat_id=chat_id, session_id=session_id, **row)
                for row in requests
            )
            session.add_all(
                Contributor(user_id=user_id, chat_id=chat_id, session_id=session_id, **row)
                for row in contributors
            )
            session.flush()
    except IntegrityError:
        # A concurrent unit stored one of these request ids first.
        return "request_conflict"
    return "replaced"


def units_for_chat(user_id: int, chat_id: str) -> list[ChatContextSessionEntity]:
    """The chat's units in display order: first request time, then session id."""
    with get_db() as session:
        return list(session.scalars(
            select(Session)
            .where(Session.user_id == user_id, Session.chat_id == chat_id)
            .order_by(func.coalesce(Session.started_at, ""), Session.session_id)
        ).all())


def request_page(user_id: int, chat_id: str, live_sessions: list[str], offset: int, limit: int):
    """(rows, total) for the live units, in unit order then sequence.

    `live_sessions` is already in display order; the position of a row's
    session in it is the first sort key, so the order is total and stable.
    """
    if not live_sessions:
        return [], 0
    where = (
        Request.user_id == user_id,
        Request.chat_id == chat_id,
        Request.session_id.in_(live_sessions),
    )
    position = case({sid: index for index, sid in enumerate(live_sessions)}, value=Request.session_id)
    with get_db() as session:
        total = session.scalar(select(func.count()).select_from(Request).where(*where))
        rows = list(session.scalars(
            select(Request).where(*where)
            .order_by(position, Request.sequence)
            .offset(offset).limit(limit)
        ).all())
    return rows, int(total or 0)


def top_contributors(user_id: int, chat_id: str, live_sessions: list[str], by: str, limit: int):
    """Largest contributors of the live units, by size or by size x exposure."""
    if not live_sessions:
        return []
    weight = Contributor.bytes if by == "size" else Contributor.bytes * Contributor.exposure_requests
    with get_db() as session:
        return list(session.scalars(
            select(Contributor)
            .where(Contributor.user_id == user_id, Contributor.chat_id == chat_id,
                   Contributor.session_id.in_(live_sessions))
            .order_by(weight.desc(), Contributor.introduced_request, Contributor.session_id,
                      Contributor.occurrence_id)
            .limit(limit)
        ).all())


def chat_has_usage(user_id: int, chat_id: str) -> bool:
    """Whether 3729 usage rows exist for the chat (it ran, analysis not yet in)."""
    with get_db() as session:
        return bool(session.scalar(select(exists().where(
            ChatRequestUsageEntity.user_id == user_id,
            ChatRequestUsageEntity.chat_id == chat_id,
        ))))
