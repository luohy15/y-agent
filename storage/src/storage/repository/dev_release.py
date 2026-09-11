"""Publication-slot repository: one locked transaction per transition (todo 3493).

Every write here is a single PostgreSQL transaction that (1) makes the slot row
exist with ``INSERT ... ON CONFLICT DO NOTHING``, (2) takes a row lock with
``SELECT ... FOR UPDATE``, (3) checks the optimistic preconditions and the
request-idempotency history, and (4) applies the state change together with its
audit record. There is deliberately no read-then-save in the service layer: the
unique constraint serializes the first acquisition of a project, and the row
lock serializes every later transition.

This module requires PostgreSQL. It does not emulate the conflict/locking
semantics on other dialects, because a claim that appears to succeed without
them is worse than an error.
"""

import uuid
from typing import Callable, List, Optional, Tuple

from sqlalchemy.dialects.postgresql import insert as pg_insert

from storage.database.base import get_db
from storage.dto.dev_release import DevRelease, DevReleaseTransition, DevReleaseWaiter
from storage.entity.chat import ChatEntity
from storage.entity.dev_release import DevReleaseEntity
from storage.entity.dev_release_waiter import DevReleaseWaiterEntity
from storage.entity.todo import TodoEntity
from storage.entity.user import UserEntity
from storage.util import get_unix_timestamp, get_utc_iso8601_timestamp

# Transition history is low-volume coordination metadata, not a log stream. The
# cap keeps a long-lived slot's row bounded; only the most recent entry is ever
# needed for replay detection, and older request ids can no longer match a
# current generation anyway.
MAX_HISTORY_ENTRIES = 200

# The queue is bounded and never evicts: an overflowing project is a signal
# that publication is stuck, not something to silently drop a waiter over.
MAX_PENDING_WAITERS = 100


class DevReleaseError(Exception):
    def __init__(self, reason: str, current: Optional[DevRelease] = None):
        super().__init__(reason)
        self.reason = reason
        self.current = current


class DevReleaseConflict(DevReleaseError):
    """A precondition on the current slot state failed (HTTP 409)."""


class DevReleaseDenied(DevReleaseError):
    """The caller is not the owning account / owner session (HTTP 403)."""


class DevReleaseInvalid(DevReleaseError):
    """The request is not well-formed for the locked state (HTTP 422)."""


def _entity_to_dto(session, entity: DevReleaseEntity) -> DevRelease:
    owner_user_id = None
    if entity.user_id is not None:
        owner_user_id = (
            session.query(UserEntity.user_id).filter(UserEntity.id == entity.user_id).scalar()
        )
    return DevRelease(
        project_key=entity.project_key,
        generation=entity.generation,
        active=bool(entity.active),
        claim_id=entity.claim_id,
        owner_user_id=owner_user_id,
        owner_trace_id=entity.owner_trace_id,
        owner_chat_id=entity.owner_chat_id,
        publisher_chat_id=entity.publisher_chat_id,
        target=entity.target,
        waiters=list(entity.waiters or []),
        history=[DevReleaseTransition.from_dict(h) for h in (entity.history or [])],
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        created_at_unix=entity.created_at_unix,
        updated_at_unix=entity.updated_at_unix,
    )


def absent_slot(project_key: str) -> DevRelease:
    """An unclaimed project is an inactive slot at generation 0."""
    return DevRelease(project_key=project_key)


def get_slot(project_key: str) -> DevRelease:
    with get_db() as session:
        row = session.query(DevReleaseEntity).filter_by(project_key=project_key).first()
        return _entity_to_dto(session, row) if row else absent_slot(project_key)


def list_active(limit: int = 50) -> List[DevRelease]:
    with get_db() as session:
        rows = (
            session.query(DevReleaseEntity)
            .filter(DevReleaseEntity.active.is_(True))
            .order_by(DevReleaseEntity.project_key)
            .limit(limit)
            .all()
        )
        return [_entity_to_dto(session, row) for row in rows]


def _ensure_and_lock(session, project_key: str) -> DevReleaseEntity:
    now, now_unix = get_utc_iso8601_timestamp(), get_unix_timestamp()
    session.execute(
        pg_insert(DevReleaseEntity.__table__)
        .values(
            project_key=project_key,
            generation=0,
            active=False,
            history=[],
            waiters=[],
            created_at=now,
            updated_at=now,
            created_at_unix=now_unix,
            updated_at_unix=now_unix,
        )
        .on_conflict_do_nothing(index_elements=["project_key"])
    )
    return (
        session.query(DevReleaseEntity)
        .filter_by(project_key=project_key)
        .populate_existing()
        .with_for_update()
        .one()
    )


def _replay(row: DevReleaseEntity, operation: str, actor_user_id: str, request_id: str,
            params: dict, preconditions: dict) -> Optional[bool]:
    """Classify a request id already present in the transition history.

    Returns True when it is an exact retry of the latest transition (which must
    be answered with the current state and no second transition), and raises for
    a reuse with different parameters or a replay that has since been
    superseded. Returns None when the request id is new.
    """
    history = row.history or []
    # Only the latest entry can be an accepted retry, so trimming old entries
    # (MAX_HISTORY_ENTRIES) cannot turn a stale replay into a re-execution: its
    # generation and claim id no longer match.
    for index, entry in enumerate(history):
        if entry.get('request_id') != request_id:
            continue
        if index != len(history) - 1:
            raise DevReleaseConflict("request_id replay was superseded by a later transition")
        same = (
            entry.get('operation') == operation
            and entry.get('actor_user_id') == actor_user_id
            and (entry.get('params') or {}) == params
            # Same request against the same expected state: a retry carrying
            # different preconditions is a different request, not a replay.
            and (entry.get('preconditions') or {}) == preconditions
        )
        if not same:
            raise DevReleaseConflict(
                "request_id was already used for a different operation, actor or parameters"
            )
        return True
    return None


def apply_transition(
    *,
    project_key: str,
    operation: str,
    user_id: int,
    actor_user_id: str,
    request_id: str,
    expected_generation: int,
    claim_id: Optional[str],
    params: dict,
    mutate: Callable[[object, DevReleaseEntity], Optional[dict]],
    require_owner_account: bool = True,
) -> Tuple[DevRelease, bool]:
    """Run one audited transition under the slot's row lock.

    Returns ``(slot, applied)``; ``applied`` is False for an exact retry of the
    latest transition, which returns the current state unchanged.
    """
    with get_db() as session:
        row = _ensure_and_lock(session, project_key)

        def current() -> DevRelease:
            return _entity_to_dto(session, row)

        preconditions = {"expected_generation": expected_generation, "claim_id": claim_id}
        try:
            if _replay(row, operation, actor_user_id, request_id, params, preconditions):
                return current(), False
        except DevReleaseError as exc:
            exc.current = current()
            raise

        if require_owner_account and row.active and row.user_id != user_id:
            raise DevReleaseDenied("the active claim belongs to another account", current())
        if row.generation != expected_generation:
            raise DevReleaseConflict(
                f"expected generation {expected_generation}, slot is at {row.generation}", current()
            )
        if claim_id is not None and row.claim_id != claim_id:
            raise DevReleaseConflict("claim_id does not match the current claim", current())

        try:
            # `mutate` returns the audit extras for this transition:
            # {"previous": ..., "grant": ...}. Both are optional.
            extras = mutate(session, row) or {}
        except DevReleaseError as exc:
            exc.current = current()
            raise

        row.generation = row.generation + 1
        _append_transition(row, DevReleaseTransition(
            timestamp=get_utc_iso8601_timestamp(),
            unix_timestamp=get_unix_timestamp(),
            operation=operation,
            request_id=request_id,
            actor_user_id=actor_user_id,
            generation=row.generation,
            params=params,
            preconditions=preconditions,
            previous=extras.get("previous"),
            grant=extras.get("grant"),
            rejected=extras.get("rejected"),
        ))
        session.flush()
        return current(), True


def _append_transition(row: DevReleaseEntity, entry: DevReleaseTransition) -> None:
    history = list(row.history or [])
    history.append(entry.to_dict())
    row.history = history[-MAX_HISTORY_ENTRIES:]


def _require_owner_session(row: DevReleaseEntity, trace_id: str, chat_id: str) -> None:
    if not row.active:
        raise DevReleaseConflict("project has no active claim")
    if row.owner_trace_id != trace_id or row.owner_chat_id != chat_id:
        raise DevReleaseDenied("actor is not the current owner session")


def claim(*, project_key: str, user_id: int, actor_user_id: str, request_id: str,
          expected_generation: int, owner_trace_id: str, owner_chat_id: str,
          target: Optional[str]) -> Tuple[DevRelease, bool]:
    def mutate(session, row: DevReleaseEntity):
        if row.active:
            raise DevReleaseConflict("project is already claimed")
        if row.waiters:
            # FIFO is the whole point: a direct claim must not cut the queue.
            raise DevReleaseConflict(
                "project has pending waiters; use enqueue to take your turn"
            )
        row.user_id = user_id
        row.claim_id = str(uuid.uuid4())
        row.active = True
        row.owner_trace_id = owner_trace_id
        row.owner_chat_id = owner_chat_id
        row.publisher_chat_id = None
        row.target = target
        return None

    return apply_transition(
        project_key=project_key, operation="claim", user_id=user_id,
        actor_user_id=actor_user_id, request_id=request_id,
        expected_generation=expected_generation, claim_id=None,
        params={"owner_trace_id": owner_trace_id, "owner_chat_id": owner_chat_id,
                "target": target},
        mutate=mutate,
        # A competing account acquiring a free slot is a conflict, not a
        # permission error; only mutations of an existing claim are account-bound.
        require_owner_account=False,
    )


def release(*, project_key: str, user_id: int, actor_user_id: str, request_id: str,
            expected_generation: int, claim_id: str, trace_id: str, chat_id: str,
            outcome_reference: str, quiescence_evidence: str) -> Tuple[DevRelease, bool]:
    def mutate(session, row: DevReleaseEntity):
        _require_owner_session(row, trace_id, chat_id)
        previous = {
            "claim_id": row.claim_id,
            "owner_trace_id": row.owner_trace_id,
            "owner_chat_id": row.owner_chat_id,
            "publisher_chat_id": row.publisher_chat_id,
            "target": row.target,
        }
        row.active = False
        row.user_id = None
        row.claim_id = None
        row.owner_trace_id = None
        row.owner_chat_id = None
        row.publisher_chat_id = None
        row.target = None
        # Release and grant are one transition: the slot never shows a free
        # window that a direct claim could take from the waiter at the head.
        granted, rejected = _grant_head(session, row)
        return {"previous": previous, "grant": _grant_record(session, granted),
                "rejected": rejected}

    return apply_transition(
        project_key=project_key, operation="release", user_id=user_id,
        actor_user_id=actor_user_id, request_id=request_id,
        expected_generation=expected_generation, claim_id=claim_id,
        params={"trace_id": trace_id, "chat_id": chat_id,
                "outcome_reference": outcome_reference,
                "quiescence_evidence": quiescence_evidence},
        mutate=mutate,
    )


def handoff(*, project_key: str, user_id: int, actor_user_id: str, request_id: str,
            expected_generation: int, claim_id: str, trace_id: str, chat_id: str,
            new_owner_chat_id: str) -> Tuple[DevRelease, bool]:
    def mutate(session, row: DevReleaseEntity):
        _require_owner_session(row, trace_id, chat_id)
        previous = {"owner_chat_id": row.owner_chat_id}
        # Same trace, same account, same claim, existing publisher preserved:
        # a handoff moves the owning session, it never opens the slot.
        row.owner_chat_id = new_owner_chat_id
        return {"previous": previous}

    return apply_transition(
        project_key=project_key, operation="handoff", user_id=user_id,
        actor_user_id=actor_user_id, request_id=request_id,
        expected_generation=expected_generation, claim_id=claim_id,
        params={"trace_id": trace_id, "chat_id": chat_id,
                "new_owner_chat_id": new_owner_chat_id},
        mutate=mutate,
    )


def set_publisher(*, project_key: str, user_id: int, actor_user_id: str, request_id: str,
                  expected_generation: int, claim_id: str, trace_id: str, chat_id: str,
                  publisher_chat_id: Optional[str],
                  quiescence_evidence: Optional[str]) -> Tuple[DevRelease, bool]:
    def mutate(session, row: DevReleaseEntity):
        _require_owner_session(row, trace_id, chat_id)
        if row.publisher_chat_id is not None and row.publisher_chat_id != publisher_chat_id:
            # Replacing or clearing a delegate means the previous publisher's
            # external work must already be quiescent; a session simply ending
            # is not evidence of that.
            if not quiescence_evidence:
                raise DevReleaseInvalid(
                    "quiescence_evidence is required to replace or clear the current publisher"
                )
        previous = {"publisher_chat_id": row.publisher_chat_id}
        row.publisher_chat_id = publisher_chat_id
        return {"previous": previous}

    return apply_transition(
        project_key=project_key, operation="publisher", user_id=user_id,
        actor_user_id=actor_user_id, request_id=request_id,
        expected_generation=expected_generation, claim_id=claim_id,
        params={"trace_id": trace_id, "chat_id": chat_id,
                "publisher_chat_id": publisher_chat_id,
                "quiescence_evidence": quiescence_evidence},
        mutate=mutate,
    )


def takeover(*, project_key: str, user_id: int, actor_user_id: str, request_id: str,
             expected_generation: int, claim_id: str, new_owner_trace_id: str,
             new_owner_chat_id: str, authorization_reference: str,
             quiescence_evidence: str) -> Tuple[DevRelease, bool]:
    def mutate(session, row: DevReleaseEntity):
        if not row.active:
            raise DevReleaseConflict("project has no active claim to take over")
        previous = {
            "claim_id": row.claim_id,
            "owner_trace_id": row.owner_trace_id,
            "owner_chat_id": row.owner_chat_id,
            "publisher_chat_id": row.publisher_chat_id,
        }
        # A new claim identity, so any request still carrying the old claim id
        # fails even though the slot never opened.
        row.claim_id = str(uuid.uuid4())
        row.owner_trace_id = new_owner_trace_id
        row.owner_chat_id = new_owner_chat_id
        row.publisher_chat_id = None
        return {"previous": previous}

    return apply_transition(
        project_key=project_key, operation="takeover", user_id=user_id,
        actor_user_id=actor_user_id, request_id=request_id,
        expected_generation=expected_generation, claim_id=claim_id,
        params={"new_owner_trace_id": new_owner_trace_id,
                "new_owner_chat_id": new_owner_chat_id,
                "authorization_reference": authorization_reference,
                "quiescence_evidence": quiescence_evidence},
        mutate=mutate,
    )


# ---------------------------------------------------------------------------
# Waiter queue (todo 3493 revision)
#
# Queue edits are ownership-neutral: they take the same slot row lock, but they
# never touch `generation` and never require the current owner's generation, so
# enqueueing behind a publisher cannot invalidate that publisher's in-flight
# release or check. Only a grant is an ownership transition, and it increments
# the generation exactly once -- including when it rides along with a release.
# ---------------------------------------------------------------------------


def _public_user_id(session, internal_user_id: Optional[int]) -> Optional[str]:
    if internal_user_id is None:
        return None
    return session.query(UserEntity.user_id).filter(UserEntity.id == internal_user_id).scalar()


def _waiter_to_dto(session, row: DevReleaseWaiterEntity,
                   position: Optional[int] = None) -> DevReleaseWaiter:
    return DevReleaseWaiter(
        project_key=row.project_key,
        waiter_id=row.waiter_id,
        request_id=row.request_id,
        user_id=_public_user_id(session, row.user_id),
        trace_id=row.trace_id,
        chat_id=row.chat_id,
        status=row.status,
        authorization_reference=row.authorization_reference,
        baseline_sha=row.baseline_sha,
        candidate_sha=row.candidate_sha,
        todo_ids=list(row.todo_ids or []),
        target=row.target,
        position=position,
        rejected_reason=row.rejected_reason,
        granted_claim_id=row.granted_claim_id,
        granted_generation=row.granted_generation,
        event_id=row.event_id,
        delivery_state=row.delivery_state,
        enqueue_needed=row.enqueue_needed,
        delivery_attempts=row.delivery_attempts or 0,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_at_unix=row.created_at_unix,
        updated_at_unix=row.updated_at_unix,
    )


def _position(row: DevReleaseEntity, waiter_id: str) -> Optional[int]:
    waiters = list(row.waiters or [])
    return waiters.index(waiter_id) + 1 if waiter_id in waiters else None


def _validate_coordinator(session, user_id: int, trace_id: str, chat_id: str) -> Optional[str]:
    """Reason this coordinator session cannot hold the slot, or None.

    Shared by registration and by re-validation at grant time, so a waiter that
    became unusable while queued is rejected instead of being handed a claim.
    Chat *state* is deliberately not consulted: idle or running says nothing
    about whether the coordinator may own the publication.
    """
    chat = (session.query(ChatEntity.topic)
            .filter_by(user_id=user_id, chat_id=chat_id, trace_id=trace_id).first())
    if chat is None:
        return f"chat {chat_id!r} is not a chat of this account in trace {trace_id!r}"
    if chat.topic == "manager":
        return "a root-topic chat cannot be a publication coordinator"
    todo = session.query(TodoEntity.id).filter_by(user_id=user_id, todo_id=trace_id).first()
    if todo is None:
        return f"trace {trace_id!r} has no todo for this account"
    return None


def _grant_head(session, row: DevReleaseEntity) -> Tuple[Optional[DevReleaseWaiterEntity], List[dict]]:
    """Install the first still-valid pending waiter as owner; return its receipt.

    Entries that were cancelled, already served or have become invalid are
    resolved in place and skipped, so one broken waiter cannot block everyone
    behind it. The rejected ones are reported alongside the grant so the caller
    can unpark their traces. The caller increments `generation` exactly once.
    """
    waiters = list(row.waiters or [])
    granted, rejected = None, []
    while waiters:
        waiter_id = waiters.pop(0)
        receipt = (session.query(DevReleaseWaiterEntity)
                   .filter_by(project_key=row.project_key, waiter_id=waiter_id).first())
        if receipt is None or receipt.status != "pending":
            continue
        reason = _validate_coordinator(session, receipt.user_id, receipt.trace_id, receipt.chat_id)
        if reason:
            receipt.status = "rejected"
            receipt.rejected_reason = reason
            rejected.append({"waiter_id": receipt.waiter_id,
                             "user_id": _public_user_id(session, receipt.user_id),
                             "trace_id": receipt.trace_id, "reason": reason})
            continue
        row.user_id = receipt.user_id
        row.claim_id = str(uuid.uuid4())
        row.active = True
        row.owner_trace_id = receipt.trace_id
        row.owner_chat_id = receipt.chat_id
        row.publisher_chat_id = None
        row.target = receipt.target
        receipt.status = "granted"
        receipt.granted_claim_id = row.claim_id
        # The caller bumps by exactly one right after this returns.
        receipt.granted_generation = row.generation + 1
        # The wakeup is durable from this same transaction on: delivery is
        # attempted only after commit, and a lost response cannot drop it.
        receipt.event_id = str(uuid.uuid4())
        receipt.delivery_state = "pending"
        receipt.delivery_attempts = 0
        receipt.last_error = None
        granted = receipt
        break
    row.waiters = waiters
    return granted, rejected


def _grant_record(session, receipt: Optional[DevReleaseWaiterEntity]) -> Optional[dict]:
    if receipt is None:
        return None
    return {
        "waiter_id": receipt.waiter_id,
        "user_id": _public_user_id(session, receipt.user_id),
        "trace_id": receipt.trace_id,
        "chat_id": receipt.chat_id,
        "claim_id": receipt.granted_claim_id,
        "generation": receipt.granted_generation,
        "target": receipt.target,
        "event_id": receipt.event_id,
        "authorization_reference": receipt.authorization_reference,
    }


def _registration_matches(receipt: DevReleaseWaiterEntity, **fields) -> bool:
    return all(getattr(receipt, key) == value for key, value in fields.items())


def enqueue(*, project_key: str, user_id: int, actor_user_id: str, waiter_id: str,
            request_id: str, trace_id: str, chat_id: str, target: Optional[str],
            authorization_reference: str, baseline_sha: str, candidate_sha: str,
            todo_ids: List[str]) -> Tuple[DevRelease, DevReleaseWaiter, str]:
    """Atomic acquire-or-enqueue: register in FIFO order, grant if free.

    Returns (slot, waiter, outcome) where outcome is ``granted`` (this call took
    ownership), ``queued`` (registered, wait for the wakeup) or ``unchanged``
    (an exact retry of a registration that already exists).
    """
    registration = dict(
        request_id=request_id, user_id=user_id, trace_id=trace_id, chat_id=chat_id,
        target=target, authorization_reference=authorization_reference,
        baseline_sha=baseline_sha, candidate_sha=candidate_sha,
    )
    with get_db() as session:
        row = _ensure_and_lock(session, project_key)

        def current() -> DevRelease:
            return _entity_to_dto(session, row)

        existing = (session.query(DevReleaseWaiterEntity)
                    .filter_by(project_key=project_key, waiter_id=waiter_id).first())
        if existing is not None:
            if not _registration_matches(existing, **registration) or \
                    list(existing.todo_ids or []) != list(todo_ids):
                raise DevReleaseConflict(
                    "waiter_id was already registered with different parameters", current())
            # An exact retry -- including one arriving long after the id left
            # the FIFO -- reports the receipt's current state and registers
            # nothing new.
            return current(), _waiter_to_dto(session, existing, _position(row, waiter_id)), "unchanged"

        reused = (session.query(DevReleaseWaiterEntity)
                  .filter_by(project_key=project_key, request_id=request_id).first())
        if reused is not None:
            raise DevReleaseConflict("request_id was already used by another waiter", current())

        reason = _validate_coordinator(session, user_id, trace_id, chat_id)
        if reason:
            raise DevReleaseInvalid(reason)

        pending = (session.query(DevReleaseWaiterEntity)
                   .filter_by(project_key=project_key, user_id=user_id, trace_id=trace_id,
                              status="pending").first())
        if pending is not None:
            raise DevReleaseConflict(
                f"trace {trace_id!r} already has waiter {pending.waiter_id!r} pending", current())
        if row.active and row.user_id == user_id and row.owner_trace_id == trace_id:
            raise DevReleaseConflict(f"trace {trace_id!r} already owns this project", current())
        if len(row.waiters or []) >= MAX_PENDING_WAITERS:
            raise DevReleaseConflict(
                f"waiter queue is full ({MAX_PENDING_WAITERS} pending)", current())

        session.add(DevReleaseWaiterEntity(
            project_key=project_key, waiter_id=waiter_id, status="pending",
            todo_ids=list(todo_ids), delivery_attempts=0, **registration,
        ))
        row.waiters = [*(row.waiters or []), waiter_id]
        session.flush()

        outcome = "queued"
        rejected = []
        if not row.active:
            granted, rejected = _grant_head(session, row)
            if granted is not None:
                row.generation = row.generation + 1
                _append_transition(row, DevReleaseTransition(
                    timestamp=get_utc_iso8601_timestamp(),
                    unix_timestamp=get_unix_timestamp(),
                    operation="grant",
                    request_id=request_id,
                    actor_user_id=actor_user_id,
                    generation=row.generation,
                    params={"waiter_id": granted.waiter_id},
                    grant=_grant_record(session, granted),
                    rejected=rejected,
                ))
                if granted.waiter_id == waiter_id:
                    outcome = "granted"
        session.flush()
        receipt = (session.query(DevReleaseWaiterEntity)
                   .filter_by(project_key=project_key, waiter_id=waiter_id).one())
        return current(), _waiter_to_dto(session, receipt, _position(row, waiter_id)), outcome


def cancel_waiter(*, project_key: str, user_id: int, waiter_id: str, request_id: str,
                  trace_id: str, chat_id: str) -> Tuple[DevRelease, DevReleaseWaiter, str]:
    """Withdraw a pending registration. An already-granted claim is never released."""
    with get_db() as session:
        row = _ensure_and_lock(session, project_key)

        def current() -> DevRelease:
            return _entity_to_dto(session, row)

        receipt = (session.query(DevReleaseWaiterEntity)
                   .filter_by(project_key=project_key, waiter_id=waiter_id).first())
        if receipt is None:
            raise DevReleaseInvalid(f"unknown waiter {waiter_id!r} for {project_key}")
        if receipt.user_id != user_id:
            raise DevReleaseDenied("the waiter belongs to another account")
        if (receipt.trace_id, receipt.chat_id) != (trace_id, chat_id):
            raise DevReleaseDenied("actor is not the registering session")
        if receipt.status == "granted":
            raise DevReleaseConflict(
                "waiter was already granted ownership; release it instead", current())
        if receipt.status != "pending":
            return current(), _waiter_to_dto(session, receipt), "unchanged"

        receipt.status = "cancelled"
        receipt.cancel_request_id = request_id
        row.waiters = [w for w in (row.waiters or []) if w != waiter_id]
        session.flush()
        return current(), _waiter_to_dto(session, receipt), "cancelled"


def get_waiter(project_key: str, waiter_id: str) -> Optional[DevReleaseWaiter]:
    with get_db() as session:
        row = (session.query(DevReleaseWaiterEntity)
               .filter_by(project_key=project_key, waiter_id=waiter_id).first())
        if row is None:
            return None
        slot = (session.query(DevReleaseEntity)
                .filter_by(project_key=project_key).first())
        position = _position(slot, waiter_id) if slot is not None else None
        return _waiter_to_dto(session, row, position)


def list_waiters(user_id: int, *, project_key: Optional[str] = None,
                 limit: int = 50) -> List[DevReleaseWaiter]:
    """This account's own receipts. Never another account's."""
    with get_db() as session:
        query = session.query(DevReleaseWaiterEntity).filter_by(user_id=user_id)
        if project_key:
            query = query.filter_by(project_key=project_key)
        rows = query.order_by(DevReleaseWaiterEntity.id.desc()).limit(limit).all()
        slots = {}
        result = []
        for row in rows:
            if row.project_key not in slots:
                slots[row.project_key] = (session.query(DevReleaseEntity)
                                          .filter_by(project_key=row.project_key).first())
            slot = slots[row.project_key]
            result.append(_waiter_to_dto(
                session, row, _position(slot, row.waiter_id) if slot is not None else None))
        return result


def pending_wakeups(limit: int = 50) -> List[DevReleaseWaiter]:
    """Grant events that have not been confirmed delivered (outbox recovery)."""
    with get_db() as session:
        rows = (session.query(DevReleaseWaiterEntity)
                .filter(DevReleaseWaiterEntity.event_id.isnot(None))
                .filter(DevReleaseWaiterEntity.delivery_state.in_(("pending", "accepted")))
                # Fewest attempts first, so a receipt that keeps failing cannot
                # sit at the head of every batch and starve the others.
                .order_by(DevReleaseWaiterEntity.delivery_attempts, DevReleaseWaiterEntity.id)
                .limit(limit)
                .all())
        return [_waiter_to_dto(session, row) for row in rows]


def mark_delivery(project_key: str, waiter_id: str, *, state: str,
                  enqueue_needed: Optional[bool] = None, error: Optional[str] = None,
                  attempt: bool = False) -> Optional[DevReleaseWaiter]:
    """Record wakeup progress. `accepted` means the message is in the chat and
    only the broker send may still be owed."""
    with get_db() as session:
        row = (session.query(DevReleaseWaiterEntity)
               .filter_by(project_key=project_key, waiter_id=waiter_id).first())
        if row is None:
            return None
        row.delivery_state = state
        if enqueue_needed is not None:
            row.enqueue_needed = enqueue_needed
        if attempt:
            row.delivery_attempts = (row.delivery_attempts or 0) + 1
        # Keep the last failure visible while the event is still owed; only a
        # new error or a settled outcome replaces it.
        if error is not None:
            row.last_error = error
        elif state in ("sent", "superseded"):
            row.last_error = None
        session.flush()
        return _waiter_to_dto(session, row)
