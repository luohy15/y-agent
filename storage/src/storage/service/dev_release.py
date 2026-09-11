"""Publication-ownership service (todo 3493).

Everything that can be decided without the slot's row lock happens here:
canonical project identity, bounded request fields, and validating that the
supplied trace/chat attribution really refers to this account's persisted
sessions. Everything that depends on current slot state -- generation, claim
identity, owner session, evidence required to displace a publisher -- stays in
the repository's locked transaction.

Attribution, not authentication: the API credential identifies the account, and
trace/chat ids say which of that account's sessions acted. They are validated
against persisted rows, so they cannot be invented, but they are not per-session
cryptographic identities.
"""

import re
from typing import List, Optional, Tuple

from loguru import logger

from storage.dto.dev_release import DevRelease, DevReleaseWaiter
from storage.project_key import ProjectKeyError, normalize_project_key
from storage.repository import chat as chat_repo
from storage.repository import dev_release as release_repo
from storage.repository import user as user_repo
from storage.repository.dev_release import (  # noqa: F401 - re-exported for callers
    DevReleaseConflict, DevReleaseDenied, DevReleaseError, DevReleaseInvalid,
)

MAX_ID_LENGTH = 64
MAX_TARGET_LENGTH = 200
MAX_EVIDENCE_LENGTH = 500
MAX_LIST_LIMIT = 200
MAX_TODO_IDS = 20

ROLES = ("owner", "publisher")
_SHA = re.compile(r"^[0-9a-fA-F]{7,64}$")


def _text(value: Optional[str], field: str, max_length: int, *, required: bool = True) -> Optional[str]:
    text = (value or "").strip()
    if not text:
        if required:
            raise DevReleaseInvalid(f"{field} is required")
        return None
    if len(text) > max_length:
        raise DevReleaseInvalid(f"{field} must be at most {max_length} characters")
    return text


def resolve_project_key(project: str) -> str:
    try:
        return normalize_project_key(project)
    except ProjectKeyError as exc:
        raise DevReleaseInvalid(str(exc)) from exc


def actor_user_id(user_id: int, actor: Optional[str] = None) -> str:
    """Public id of the authenticated account, used for attribution and for
    filtering transition history to the entries an account itself wrote.

    A caller that already resolved it (the controller needs it for the
    response projection) passes it back in rather than paying a second lookup.
    """
    if actor:
        return actor
    user = user_repo.get_user_by_id(user_id)
    if user is None:
        raise DevReleaseInvalid("unknown account")
    return user.user_id


def _validate_session(user_id: int, trace_id: str, chat_id: str) -> None:
    """The chat must be a persisted chat of this account inside that trace."""
    chats = chat_repo.find_chats_by_trace_id(user_id, trace_id)
    if not chats:
        raise DevReleaseInvalid(f"trace {trace_id!r} has no chats for this account")
    if chat_id not in {c.chat_id for c in chats}:
        raise DevReleaseInvalid(f"chat {chat_id!r} does not participate in trace {trace_id!r}")


def _validate_chat(user_id: int, chat_id: str) -> None:
    """A delegated publisher chat is validated for ownership only: execution may
    legitimately be delegated to a session outside the owner's trace."""
    if chat_repo.get_chat_meta(user_id, chat_id) is None:
        raise DevReleaseInvalid(f"chat {chat_id!r} does not belong to this account")


def _generation(value: Optional[int]) -> int:
    if value is None:
        raise DevReleaseInvalid("expected_generation is required")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DevReleaseInvalid("expected_generation must be a non-negative integer")
    return value


def _request_id(value: Optional[str]) -> str:
    return _text(value, "request_id", MAX_ID_LENGTH)


def get_slot(project: str) -> DevRelease:
    return release_repo.get_slot(resolve_project_key(project))


def list_active(limit: int = 50) -> List[DevRelease]:
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    return release_repo.list_active(limit)


def claim(user_id: int, *, project: str, trace_id: str, chat_id: str,
          expected_generation: int, request_id: str,
          target: Optional[str] = None,
          actor: Optional[str] = None) -> Tuple[DevRelease, bool]:
    project_key = resolve_project_key(project)
    trace_id = _text(trace_id, "trace_id", MAX_ID_LENGTH)
    chat_id = _text(chat_id, "chat_id", MAX_ID_LENGTH)
    target = _text(target, "target", MAX_TARGET_LENGTH, required=False)
    _validate_session(user_id, trace_id, chat_id)
    return release_repo.claim(
        project_key=project_key, user_id=user_id, actor_user_id=actor_user_id(user_id, actor),
        request_id=_request_id(request_id), expected_generation=_generation(expected_generation),
        owner_trace_id=trace_id, owner_chat_id=chat_id, target=target,
    )


def release(user_id: int, *, project: str, trace_id: str, chat_id: str,
            expected_generation: int, claim_id: str, request_id: str,
            outcome_reference: str, quiescence_evidence: str,
            actor: Optional[str] = None) -> Tuple[DevRelease, bool]:
    project_key = resolve_project_key(project)
    trace_id = _text(trace_id, "trace_id", MAX_ID_LENGTH)
    chat_id = _text(chat_id, "chat_id", MAX_ID_LENGTH)
    _validate_session(user_id, trace_id, chat_id)
    return release_repo.release(
        project_key=project_key, user_id=user_id, actor_user_id=actor_user_id(user_id, actor),
        request_id=_request_id(request_id), expected_generation=_generation(expected_generation),
        claim_id=_text(claim_id, "claim_id", MAX_ID_LENGTH),
        trace_id=trace_id, chat_id=chat_id,
        # Release is never inferred from age, process exit or a finished chat:
        # the caller must name the terminal outcome and attest quiescence.
        outcome_reference=_text(outcome_reference, "outcome_reference", MAX_EVIDENCE_LENGTH),
        quiescence_evidence=_text(quiescence_evidence, "quiescence_evidence", MAX_EVIDENCE_LENGTH),
    )


def handoff(user_id: int, *, project: str, trace_id: str, chat_id: str,
            expected_generation: int, claim_id: str, request_id: str,
            new_owner_chat_id: str,
            actor: Optional[str] = None) -> Tuple[DevRelease, bool]:
    project_key = resolve_project_key(project)
    trace_id = _text(trace_id, "trace_id", MAX_ID_LENGTH)
    chat_id = _text(chat_id, "chat_id", MAX_ID_LENGTH)
    new_owner_chat_id = _text(new_owner_chat_id, "new_owner_chat_id", MAX_ID_LENGTH)
    _validate_session(user_id, trace_id, chat_id)
    # The successor stays inside the same trace; crossing traces is a takeover.
    _validate_session(user_id, trace_id, new_owner_chat_id)
    return release_repo.handoff(
        project_key=project_key, user_id=user_id, actor_user_id=actor_user_id(user_id, actor),
        request_id=_request_id(request_id), expected_generation=_generation(expected_generation),
        claim_id=_text(claim_id, "claim_id", MAX_ID_LENGTH),
        trace_id=trace_id, chat_id=chat_id, new_owner_chat_id=new_owner_chat_id,
    )


def set_publisher(user_id: int, *, project: str, trace_id: str, chat_id: str,
                  expected_generation: int, claim_id: str, request_id: str,
                  publisher_chat_id: Optional[str],
                  quiescence_evidence: Optional[str] = None,
                  actor: Optional[str] = None) -> Tuple[DevRelease, bool]:
    project_key = resolve_project_key(project)
    trace_id = _text(trace_id, "trace_id", MAX_ID_LENGTH)
    chat_id = _text(chat_id, "chat_id", MAX_ID_LENGTH)
    publisher_chat_id = _text(publisher_chat_id, "publisher_chat_id", MAX_ID_LENGTH, required=False)
    quiescence_evidence = _text(
        quiescence_evidence, "quiescence_evidence", MAX_EVIDENCE_LENGTH, required=False
    )
    _validate_session(user_id, trace_id, chat_id)
    if publisher_chat_id:
        _validate_chat(user_id, publisher_chat_id)
    return release_repo.set_publisher(
        project_key=project_key, user_id=user_id, actor_user_id=actor_user_id(user_id, actor),
        request_id=_request_id(request_id), expected_generation=_generation(expected_generation),
        claim_id=_text(claim_id, "claim_id", MAX_ID_LENGTH),
        trace_id=trace_id, chat_id=chat_id, publisher_chat_id=publisher_chat_id,
        quiescence_evidence=quiescence_evidence,
    )


def takeover(user_id: int, *, project: str, new_owner_trace_id: str, new_owner_chat_id: str,
             expected_generation: int, claim_id: str, request_id: str,
             authorization_reference: str, quiescence_evidence: str,
             actor: Optional[str] = None) -> Tuple[DevRelease, bool]:
    project_key = resolve_project_key(project)
    new_owner_trace_id = _text(new_owner_trace_id, "new_owner_trace_id", MAX_ID_LENGTH)
    new_owner_chat_id = _text(new_owner_chat_id, "new_owner_chat_id", MAX_ID_LENGTH)
    _validate_session(user_id, new_owner_trace_id, new_owner_chat_id)
    return release_repo.takeover(
        project_key=project_key, user_id=user_id, actor_user_id=actor_user_id(user_id, actor),
        request_id=_request_id(request_id), expected_generation=_generation(expected_generation),
        claim_id=_text(claim_id, "claim_id", MAX_ID_LENGTH),
        new_owner_trace_id=new_owner_trace_id, new_owner_chat_id=new_owner_chat_id,
        # The server records these attestations; it cannot itself verify that a
        # previous publisher's external work has really stopped.
        authorization_reference=_text(
            authorization_reference, "authorization_reference", MAX_EVIDENCE_LENGTH
        ),
        quiescence_evidence=_text(quiescence_evidence, "quiescence_evidence", MAX_EVIDENCE_LENGTH),
    )


def check(user_id: int, *, project: str, trace_id: str, chat_id: str, claim_id: str,
          expected_generation: int, role: str, actor: Optional[str] = None) -> dict:
    """Point-in-time eligibility observation. Read-only: it takes no lock, makes
    no transition, and is not a permit for whatever runs next.

    `trace_id` is always the *owning* trace, including for `role=publisher`: the
    trace is a coordinate of the claim, not of the delegate, so a publisher chat
    outside that trace still passes the owner's trace here.
    """
    if role not in ROLES:
        raise DevReleaseInvalid(f"role must be one of {', '.join(ROLES)}")
    project_key = resolve_project_key(project)
    trace_id = _text(trace_id, "trace_id", MAX_ID_LENGTH)
    chat_id = _text(chat_id, "chat_id", MAX_ID_LENGTH)
    claim_id = _text(claim_id, "claim_id", MAX_ID_LENGTH)
    generation = _generation(expected_generation)
    slot = release_repo.get_slot(project_key)

    reason = None
    if not slot.active:
        reason = "project has no active claim"
    elif slot.owner_user_id != actor_user_id(user_id, actor):
        reason = "the active claim belongs to another account"
    elif slot.claim_id != claim_id:
        reason = "claim_id does not match the current claim"
    elif slot.generation != generation:
        reason = f"expected generation {generation}, slot is at {slot.generation}"
    elif trace_id != slot.owner_trace_id:
        reason = "trace_id is not the owning trace"
    elif role == "owner":
        if chat_id != slot.owner_chat_id:
            reason = "chat_id is not the owning session"
    elif slot.publisher_chat_id:
        # A delegate exists, so only the delegate may execute.
        if chat_id != slot.publisher_chat_id:
            reason = "chat_id is not the delegated publisher"
    elif chat_id != slot.owner_chat_id:
        reason = "no publisher is delegated, so only the owner session may execute"

    return {"eligible": reason is None, "reason": reason, "role": role, "slot": slot}


# ---------------------------------------------------------------------------
# Authorized waiters (todo 3493 revision)
#
# An already-authorized coordinator enqueues once, ends its turn, and is woken
# with ownership already granted when its predecessor releases. There is no
# session-side polling, no blocking CLI wait, no question to Roy for contention
# alone, and no automatic takeover: a grant only ever follows an explicit
# release by the previous owner.
# ---------------------------------------------------------------------------


def _sha(value: Optional[str], field: str) -> str:
    text = _text(value, field, MAX_ID_LENGTH)
    if not _SHA.match(text):
        raise DevReleaseInvalid(f"{field} must be a 7-64 character hex commit id")
    return text


def _todo_ids(values) -> List[str]:
    if not values:
        raise DevReleaseInvalid("todo_ids is required")
    if len(values) > MAX_TODO_IDS:
        raise DevReleaseInvalid(f"todo_ids must name at most {MAX_TODO_IDS} todos")
    return [_text(value, "todo_ids", MAX_ID_LENGTH) for value in values]


def _set_awaiting(user_id: int, trace_id: str, *, expect: Optional[str],
                  value: Optional[str]) -> None:
    """Move a trace's inbox reason only when it is still the one we expect.

    Best effort in both directions: the slot transition is already committed
    and must never fail over the marker, and an inbox reason this feature did
    not set (a question waiting on Roy, a review handed to him) is never
    overwritten or cleared.
    """
    from storage.service import todo as todo_service
    try:
        todo = todo_service.get_todo(user_id, trace_id)
        if todo is None or todo.awaiting != expect:
            return
        todo_service.update_todo(user_id, trace_id, awaiting=value or "none")
    except Exception as exc:  # noqa: BLE001 - never fail a committed transition
        logger.warning("[dev-release] could not set trace {} awaiting={}: {}",
                       trace_id, value, exc)


def _mark_durable_wait(user_id: int, trace_id: str) -> None:
    """Make an intentional queue wait visible to the liveness watchdog.

    A queued coordinator is genuinely blocked on another session, so it is an
    explained external wait rather than unexplained silence.
    """
    _set_awaiting(user_id, trace_id, expect=None, value="external")


def _clear_durable_wait(user_id: int, trace_id: str) -> None:
    """Undo the queue park once the trace is no longer waiting in line.

    Only the `external` reason this feature parks with is cleared, and the
    grant path clears it explicitly rather than widening what `resume_work`
    means for every caller of the shared chat primitive.
    """
    _set_awaiting(user_id, trace_id, expect="external", value=None)


def _unpark_rejected(rejected) -> None:
    """Release the queue park of every waiter a transition skipped."""
    for entry in rejected or []:
        user = user_repo.get_user_by_user_id(entry.get("user_id") or "")
        if user is not None:
            _clear_durable_wait(user.id, entry["trace_id"])


def enqueue(user_id: int, *, project: str, trace_id: str, chat_id: str, waiter_id: str,
            request_id: str, authorization_reference: str, baseline_sha: str,
            candidate_sha: str, todo_ids: List[str], target: Optional[str] = None,
            actor: Optional[str] = None) -> Tuple[DevRelease, DevReleaseWaiter, str]:
    """Atomic acquire-or-enqueue for an already-authorized coordinator.

    The authorization reference and frozen candidate identity are recorded as
    the caller's attestation. The server stores and replays them; it never
    verifies that Roy authorized this delta, and a grant is not authorization
    renewal.
    """
    project_key = resolve_project_key(project)
    slot, waiter, outcome = release_repo.enqueue(
        project_key=project_key, user_id=user_id, actor_user_id=actor_user_id(user_id, actor),
        waiter_id=_text(waiter_id, "waiter_id", MAX_ID_LENGTH),
        request_id=_request_id(request_id),
        trace_id=_text(trace_id, "trace_id", MAX_ID_LENGTH),
        chat_id=_text(chat_id, "chat_id", MAX_ID_LENGTH),
        target=_text(target, "target", MAX_TARGET_LENGTH, required=False),
        authorization_reference=_text(
            authorization_reference, "authorization_reference", MAX_EVIDENCE_LENGTH),
        baseline_sha=_sha(baseline_sha, "baseline_sha"),
        candidate_sha=_sha(candidate_sha, "candidate_sha"),
        todo_ids=_todo_ids(todo_ids),
    )
    if outcome == "queued":
        _mark_durable_wait(user_id, waiter.trace_id)
    return slot, waiter, outcome


def cancel_waiter(user_id: int, *, project: str, trace_id: str, chat_id: str, waiter_id: str,
                  request_id: str) -> Tuple[DevRelease, DevReleaseWaiter, str]:
    """Withdraw a pending registration. Never releases an already-granted claim."""
    slot, waiter, outcome = release_repo.cancel_waiter(
        project_key=resolve_project_key(project), user_id=user_id,
        waiter_id=_text(waiter_id, "waiter_id", MAX_ID_LENGTH),
        request_id=_request_id(request_id),
        trace_id=_text(trace_id, "trace_id", MAX_ID_LENGTH),
        chat_id=_text(chat_id, "chat_id", MAX_ID_LENGTH),
    )
    if outcome == "cancelled":
        _clear_durable_wait(user_id, waiter.trace_id)
    return slot, waiter, outcome


def list_waiters(user_id: int, *, project: Optional[str] = None,
                 limit: int = 50) -> List[DevReleaseWaiter]:
    project_key = resolve_project_key(project) if project else None
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    return release_repo.list_waiters(user_id, project_key=project_key, limit=limit)


def grant_message(waiter: DevReleaseWaiter) -> str:
    """One line: what was granted and how to look the rest up."""
    return (
        f"Publication slot granted for {waiter.project_key}: "
        f"waiter={waiter.waiter_id} event={waiter.event_id} "
        f"claim={waiter.granted_claim_id} generation={waiter.granted_generation}. "
        f"Re-check that this claim is still active and re-verify your frozen candidate "
        f"(y dev release waiters) before any publication side effect."
    )


def _stale_grant(slot: DevRelease, waiter: DevReleaseWaiter) -> bool:
    """True when this event would report an obsolete claim as live."""
    return not (
        slot.active
        and slot.claim_id == waiter.granted_claim_id
        and slot.owner_chat_id == waiter.chat_id
        and slot.owner_trace_id == waiter.trace_id
    )


async def deliver_grant(waiter: DevReleaseWaiter, user_id: int) -> str:
    """Deliver one durable grant wakeup; return the resulting delivery state.

    Safe to call from the API right after the granting commit and from the
    worker recovery pass, and safe to call again after a crash at any point:
    the append is deduplicated by event id and the broker send is repeated only
    when this event is the one that owes it. Never raises: a failed wakeup is
    recorded for retry and never expires or reassigns the claim.
    """
    from storage.service import chat as chat_service

    if waiter.delivery_state not in ("pending", "accepted"):
        return waiter.delivery_state

    try:
        slot = release_repo.get_slot(waiter.project_key)
        if _stale_grant(slot, waiter):
            release_repo.mark_delivery(waiter.project_key, waiter.waiter_id, state="superseded")
            return "superseded"

        # A retry that already knows what it owes uses that; one that crashed
        # before recording it re-sends, because a duplicate invocation is
        # absorbed by the worker's single-chat exclusion but a lost one is not.
        if waiter.delivery_state == "accepted":
            force_send = bool(waiter.enqueue_needed)
        else:
            force_send = (waiter.delivery_attempts or 0) > 0

        release_repo.mark_delivery(waiter.project_key, waiter.waiter_id,
                                   state="pending", attempt=True)
        chat = await chat_service.get_chat(user_id, waiter.chat_id)
        if chat is None:
            raise ValueError(f"chat {waiter.chat_id!r} not found")

        # `resume_work` is the shared primitive's flag and clears `review`;
        # the queue park is this feature's own marker, so it clears it itself
        # rather than widening that flag for every caller.
        _clear_durable_wait(user_id, waiter.trace_id)
        acceptance = await chat_service.accept_dispatch(
            user_id, chat, grant_message(waiter),
            trace_id=waiter.trace_id, event_id=waiter.event_id, resume_work=True,
        )
        needs_send = force_send or not acceptance.already_running
        release_repo.mark_delivery(waiter.project_key, waiter.waiter_id,
                                   state="accepted", enqueue_needed=needs_send)
        if needs_send:
            chat_service.enqueue_chat_run(acceptance.chat, user_id=user_id,
                                          trace_id=waiter.trace_id)
        release_repo.mark_delivery(waiter.project_key, waiter.waiter_id,
                                   state="sent", enqueue_needed=False)
        return "sent"
    except Exception as exc:  # noqa: BLE001 - recorded, retried by the recovery pass
        logger.warning("[dev-release] grant wakeup deferred waiter={} error={}",
                       waiter.waiter_id, exc)
        current = release_repo.get_waiter(waiter.project_key, waiter.waiter_id)
        state = current.delivery_state if current else "pending"
        release_repo.mark_delivery(waiter.project_key, waiter.waiter_id,
                                   state=state if state in ("pending", "accepted") else "pending",
                                   error=str(exc)[:MAX_EVIDENCE_LENGTH])
        return "pending"


async def deliver_granted_waiter(slot: DevRelease) -> Optional[str]:
    """Deliver the wakeup for the waiter this transition just granted, if any.

    Also unparks the waiters it skipped. A transition that rejects waiters
    without granting one always still records its own entry (a release does),
    and an enqueue's own freshly validated waiter is always grantable, so no
    rejection can escape this hook.
    """
    entry = slot.history[-1] if slot.history else None
    if entry is None:
        return None
    _unpark_rejected(entry.rejected)
    grant = entry.grant
    if not grant:
        return None
    waiter = release_repo.get_waiter(slot.project_key, grant["waiter_id"])
    if waiter is None or waiter.delivery_state != "pending":
        return None
    user = user_repo.get_user_by_user_id(waiter.user_id)
    if user is None:
        return None
    return await deliver_grant(waiter, user.id)
