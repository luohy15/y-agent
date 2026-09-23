"""Registered scheduled chat wakeup service (todo 3655).

A session that needs a pure time wait registers a durable server-side wakeup
instead of a tmux sleep timer. Validation here mirrors the dispatch rules an
ordinary `y chat` targeting already enforces (owner scoping, no manager root),
plus the wakeup-specific bounds: the target chat must carry a trace_id
(evidence is keyed by trace) and due_at must be a bounded future instant.
"""

from datetime import datetime, timezone
from typing import List, Optional

from loguru import logger

from storage.dto.chat_wakeup import ChatWakeup
from storage.repository import chat_wakeup as wakeup_repo
from storage.util import generate_id, get_unix_timestamp

# A3: bounded default horizon. A pending wakeup suppresses the watchdog for
# its entire horizon, so this caps how long fault detection can be delayed by
# a registered wakeup (the target session is still woken at due_at regardless).
MAX_HORIZON_SECONDS = 7 * 24 * 60 * 60


class ChatWakeupInvalid(ValueError):
    """Caller error: maps to HTTP 400."""


def _parse_due_at(due_at: str) -> int:
    """Parse a fully-qualified UTC ISO 8601 instant (as the CLI resolves
    `--at` to) into unix milliseconds. Timezone interpretation of a relative
    or naive value happens client-side; this only accepts an instant."""
    try:
        value = due_at.replace("Z", "+00:00") if due_at.endswith("Z") else due_at
        dt = datetime.fromisoformat(value)
    except (ValueError, AttributeError) as exc:
        raise ChatWakeupInvalid(f"cannot parse due_at: {due_at!r}") from exc
    if dt.tzinfo is None:
        raise ChatWakeupInvalid("due_at must include a timezone offset (UTC 'Z' or explicit offset)")
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


async def create_wakeup(user_id: int, chat_id: str, message: str, due_at: str, *,
                        trace_id: Optional[str] = None, from_chat_id: Optional[str] = None,
                        from_topic: Optional[str] = None) -> ChatWakeup:
    from storage.service import chat as chat_service

    if not (message or "").strip():
        raise ChatWakeupInvalid("message is required")

    chat = await chat_service.get_chat(user_id, chat_id)
    if chat is None:
        raise ChatWakeupInvalid(f"chat '{chat_id}' not found")
    try:
        chat_service.validate_dispatch_target(chat)
    except ValueError as exc:
        raise ChatWakeupInvalid(str(exc)) from exc
    if not chat.trace_id:
        raise ChatWakeupInvalid("target chat has no trace_id; a wakeup requires a traced chat")
    if trace_id and trace_id != chat.trace_id:
        raise ChatWakeupInvalid("trace_id does not match the chat's trace")

    due_at_unix = _parse_due_at(due_at)
    now_ms = get_unix_timestamp()
    if due_at_unix <= now_ms:
        raise ChatWakeupInvalid("due_at must be in the future")
    if due_at_unix - now_ms > MAX_HORIZON_SECONDS * 1000:
        raise ChatWakeupInvalid(f"due_at must be at most {MAX_HORIZON_SECONDS // 86400} days out")

    return wakeup_repo.create_wakeup(
        user_id, generate_id(), chat_id, chat.trace_id, message, due_at_unix,
        from_chat_id=from_chat_id, from_topic=from_topic,
    )


def get_wakeup(user_id: int, wakeup_id: str) -> Optional[ChatWakeup]:
    return wakeup_repo.get_wakeup(user_id, wakeup_id)


def list_wakeups(user_id: int, *, trace_id: Optional[str] = None, all_statuses: bool = False,
                 limit: int = 50) -> List[ChatWakeup]:
    return wakeup_repo.list_wakeups(user_id, trace_id=trace_id, all_statuses=all_statuses, limit=limit)


def cancel_wakeup(user_id: int, wakeup_id: str) -> Optional[ChatWakeup]:
    """Cancel a pending wakeup. Returns None for both "not found" and "not
    pending" -- the caller (API) tells these apart with its own lookup."""
    return wakeup_repo.cancel_wakeup(user_id, wakeup_id)


def due_wakeups(limit: int = 50) -> List[ChatWakeup]:
    return wakeup_repo.due_wakeups(limit)


async def deliver_wakeup(wakeup: ChatWakeup, user_id: int) -> str:
    """Deliver one due wakeup; return the resulting status.

    Safe to call right after creation and from the scheduled delivery pass,
    and safe to call again after a crash at any point: the append is
    deduplicated by event id (the wakeup_id itself) and the broker send is
    repeated only when this event still owes it. Never raises: a failed
    delivery is recorded for retry.
    """
    from storage.service import chat as chat_service

    try:
        with wakeup_repo.delivery_transaction(user_id, wakeup.wakeup_id) as (session, row):
            if row is None:
                return "cancelled"
            if row.status not in ("pending", "accepted"):
                return row.status
            row.delivery_attempts = (row.delivery_attempts or 0) + 1
            if row.status == "pending":
                chat = await chat_service.get_chat(user_id, row.chat_id)
                if chat is None:
                    raise ValueError(f"chat {row.chat_id!r} not found")
                # Machine provenance: never auto-resume awaiting. The append,
                # run reservation and receipt commit atomically; a crash rolls
                # them all back, so cancellation cannot win after an append.
                acceptance = await chat_service.accept_dispatch(
                    user_id, chat, row.message,
                    from_chat_id=row.from_chat_id, from_topic=row.from_topic,
                    trace_id=row.trace_id, event_id=row.wakeup_id, session=session,
                )
                row.status = "accepted"
                row.enqueue_needed = not acceptance.already_running

        # Commit acceptance before sending. Serialize retry senders too, and
        # never re-accept a committed event or downgrade it to pending.
        with wakeup_repo.delivery_transaction(user_id, wakeup.wakeup_id) as (session, row):
            if row.status != "accepted":
                return row.status
            if row.enqueue_needed:
                chat = await chat_service.get_chat(user_id, row.chat_id)
                if chat is None:
                    raise ValueError(f"chat {row.chat_id!r} not found")
                chat_service.enqueue_chat_run(chat, user_id=user_id, trace_id=row.trace_id)
            row.status = "delivered"
            row.enqueue_needed = False
            row.last_error = None
        return "delivered"
    except Exception as exc:  # noqa: BLE001 - recorded, retried by the scheduled pass
        logger.warning("[chat-wakeup] delivery deferred wakeup={} error={}", wakeup.wakeup_id, exc)
        wakeup_repo.mark_delivery(
            user_id, wakeup.wakeup_id, state="pending", error=str(exc)[:500], attempt=True,
        )
        return "pending"
