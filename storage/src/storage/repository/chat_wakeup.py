"""Durable registered scheduled chat wakeup repository (todo 3655).

Cancellation and dispatch acceptance share the receipt row lock.
"""

from contextlib import contextmanager
from typing import List, Optional, Set, Tuple

from storage.database.base import get_db
from storage.dto.chat_wakeup import ChatWakeup
from storage.entity.chat_wakeup import ChatWakeupEntity
from storage.entity.user import UserEntity
from storage.util import get_unix_timestamp

# Kept equal to worker.steps.check_trace_liveness.IDLE_GRACE_SECONDS;
# worker/tests/test_watchdog_wakeup_evidence_3655.py asserts this contract.
EVIDENCE_GRACE_SECONDS = 5 * 60


def _public_user_id(session, internal_user_id: Optional[int]) -> Optional[str]:
    if internal_user_id is None:
        return None
    return session.query(UserEntity.user_id).filter(UserEntity.id == internal_user_id).scalar()


def _entity_to_dto(session, row: ChatWakeupEntity) -> ChatWakeup:
    return ChatWakeup(
        wakeup_id=row.wakeup_id,
        user_id=_public_user_id(session, row.user_id),
        chat_id=row.chat_id,
        trace_id=row.trace_id,
        message=row.message,
        due_at_unix=row.due_at_unix,
        status=row.status,
        from_chat_id=row.from_chat_id,
        from_topic=row.from_topic,
        enqueue_needed=row.enqueue_needed,
        delivery_attempts=row.delivery_attempts or 0,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_at_unix=row.created_at_unix,
        updated_at_unix=row.updated_at_unix,
    )


def create_wakeup(user_id: int, wakeup_id: str, chat_id: str, trace_id: str, message: str,
                  due_at_unix: int, *, from_chat_id: Optional[str] = None,
                  from_topic: Optional[str] = None) -> ChatWakeup:
    with get_db() as session:
        entity = ChatWakeupEntity(
            user_id=user_id, wakeup_id=wakeup_id, chat_id=chat_id, trace_id=trace_id,
            message=message, due_at_unix=due_at_unix, from_chat_id=from_chat_id,
            from_topic=from_topic, status="pending",
        )
        session.add(entity)
        session.flush()
        return _entity_to_dto(session, entity)


def get_wakeup(user_id: int, wakeup_id: str) -> Optional[ChatWakeup]:
    with get_db() as session:
        row = session.query(ChatWakeupEntity).filter_by(user_id=user_id, wakeup_id=wakeup_id).first()
        return _entity_to_dto(session, row) if row else None


def list_wakeups(user_id: int, *, trace_id: Optional[str] = None, all_statuses: bool = False,
                 limit: int = 50) -> List[ChatWakeup]:
    with get_db() as session:
        query = session.query(ChatWakeupEntity).filter_by(user_id=user_id)
        if trace_id:
            query = query.filter_by(trace_id=trace_id)
        if not all_statuses:
            query = query.filter(ChatWakeupEntity.status.in_(("pending", "accepted")))
        query = query.order_by(ChatWakeupEntity.due_at_unix.asc()).limit(limit)
        return [_entity_to_dto(session, row) for row in query.all()]


def cancel_wakeup(user_id: int, wakeup_id: str) -> Optional[ChatWakeup]:
    """Cancel a wakeup that is still `pending`. Returns None if not found or
    not in a cancellable state (the caller distinguishes the two)."""
    with get_db() as session:
        row = lock_wakeup(session, user_id, wakeup_id)
        if row is None or row.status != "pending":
            return None
        row.status = "cancelled"
        session.flush()
        return _entity_to_dto(session, row)


def due_wakeups(limit: int = 50, now_ms: Optional[int] = None) -> List[ChatWakeup]:
    """Wakeups owed delivery right now (outbox pass). Fewest attempts first,
    so a repeatedly failing wakeup cannot starve the others out of a batch."""
    now_ms = now_ms if now_ms is not None else get_unix_timestamp()
    with get_db() as session:
        rows = (session.query(ChatWakeupEntity)
                .filter(ChatWakeupEntity.status.in_(("pending", "accepted")))
                .filter(ChatWakeupEntity.due_at_unix <= now_ms)
                .order_by(ChatWakeupEntity.delivery_attempts, ChatWakeupEntity.id)
                .limit(limit)
                .all())
        return [_entity_to_dto(session, row) for row in rows]


def lock_wakeup(session, user_id: int, wakeup_id: str):
    return (session.query(ChatWakeupEntity)
            .filter_by(user_id=user_id, wakeup_id=wakeup_id)
            .populate_existing().with_for_update().first())


@contextmanager
def delivery_transaction(user_id: int, wakeup_id: str):
    """Receipt first, then acceptance's todo/chat locks; cancel locks only receipt."""
    with get_db() as session:
        yield session, lock_wakeup(session, user_id, wakeup_id)


def mark_delivery(user_id: int, wakeup_id: str, *, state: str,
                  enqueue_needed: Optional[bool] = None, error: Optional[str] = None,
                  attempt: bool = False) -> Optional[ChatWakeup]:
    """Record retry diagnostics without reviving or regressing a receipt."""
    with delivery_transaction(user_id, wakeup_id) as (session, row):
        if row is None:
            return None
        if row.status in ("cancelled", "delivered"):
            return _entity_to_dto(session, row)
        if state == "delivered" or (state == "accepted" and row.status == "pending"):
            row.status = state
        if enqueue_needed is not None:
            row.enqueue_needed = enqueue_needed
        if attempt:
            row.delivery_attempts = (row.delivery_attempts or 0) + 1
        if error is not None:
            row.last_error = error
        elif state == "delivered":
            row.last_error = None
        session.flush()
        return _entity_to_dto(session, row)


def has_pending_wakeup(session, user_id: int, trace_id: str, now_ms: int) -> bool:
    """True while this account has a wakeup on this trace that is still
    pending/accepted and not yet past its due time plus grace.

    Used as fault-classification evidence by the trace-liveness watchdog
    (todo 3655): a session that registered a wakeup is genuinely waiting on
    the clock, so silence until due_at + grace is expected, not a fault. A
    wakeup stuck undelivered past the grace stops suppressing on its own.
    """
    cutoff_ms = now_ms - EVIDENCE_GRACE_SECONDS * 1000
    return session.query(ChatWakeupEntity.id).filter(
        ChatWakeupEntity.user_id == user_id,
        ChatWakeupEntity.trace_id == trace_id,
        ChatWakeupEntity.status.in_(("pending", "accepted")),
        ChatWakeupEntity.due_at_unix > cutoff_ms,
    ).first() is not None


def pending_wakeup_traces(session, user_ids, trace_ids, now_ms: int) -> Set[Tuple[int, str]]:
    """Batched form of `has_pending_wakeup` for the watchdog's per-pass query
    (same shape as `check_trace_liveness._chat_aggregates`)."""
    if not user_ids or not trace_ids:
        return set()
    cutoff_ms = now_ms - EVIDENCE_GRACE_SECONDS * 1000
    rows = (session.query(ChatWakeupEntity.user_id, ChatWakeupEntity.trace_id)
            .filter(ChatWakeupEntity.user_id.in_(user_ids),
                    ChatWakeupEntity.trace_id.in_(trace_ids),
                    ChatWakeupEntity.status.in_(("pending", "accepted")),
                    ChatWakeupEntity.due_at_unix > cutoff_ms)
            .distinct().all())
    return {(r[0], r[1]) for r in rows}
