"""Todo service."""

import ast
import re
from typing import List, Optional, Tuple
from loguru import logger
from storage.entity.dto import Todo, TodoHistoryEntry
from storage.repository import todo as todo_repo
from storage.repository import entity_tag as tag_repo
from storage.repository.entity_tag import normalize_tags
from storage.service import telegram as telegram_service
from storage.util import get_utc_iso8601_timestamp, get_unix_timestamp

_CHANGED_NOTE_PREFIX = "changed: "


def list_todos(
    user_id: int,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    query: Optional[str] = None,
    unread: Optional[bool] = None,
    tag: Optional[str] = None,
    on: Optional[str] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
    created_on: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_on: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Todo]:
    return todo_repo.list_todos(
        user_id,
        status=status,
        priority=priority,
        query=query,
        unread=unread,
        tag=tag,
        on=on,
        from_=from_,
        to=to,
        created_on=created_on,
        created_from=created_from,
        created_to=created_to,
        updated_on=updated_on,
        updated_from=updated_from,
        updated_to=updated_to,
        limit=limit,
        offset=offset,
    )


def get_todo(user_id: int, todo_id: str) -> Optional[Todo]:
    return todo_repo.get_todo(user_id, todo_id)


def find_todos_by_ids(user_id: int, todo_ids: List[str]) -> dict:
    """Return {todo_id: Todo} for owner-scoped tag hydration."""
    return todo_repo.find_todos_by_ids(user_id, todo_ids)


def create_todo(
    user_id: int,
    name: str,
    desc: Optional[str] = None,
    tags: Optional[List[str]] = None,
    due_date: Optional[str] = None,
    priority: Optional[str] = None,
) -> Todo:
    # Find smallest available positive integer ID for this user
    existing_ids = todo_repo.get_all_todo_ids(user_id)
    used = set()
    for tid in existing_ids:
        try:
            used.add(int(tid))
        except (ValueError, TypeError):
            pass
    next_id = 1
    while next_id in used:
        next_id += 1

    if tags is not None:
        tags = normalize_tags(tags)

    todo = Todo(
        todo_id=str(next_id),
        name=name,
        desc=desc,
        tags=tags,
        due_date=due_date,
        priority=priority,
        status="pending",
        history=[TodoHistoryEntry(timestamp=get_utc_iso8601_timestamp(), unix_timestamp=get_unix_timestamp(), action="created")],
    )
    saved = todo_repo.save_todo(user_id, todo)
    tag_repo.sync_tags(user_id, "todo", saved.todo_id, saved.tags or [])
    return saved


def _changed_progress_value(note: str) -> Optional[str]:
    """Extract the new `progress` value from an `update_todo` history note.

    `update_todo` writes notes as `"changed: field1=<repr>, field2=<repr>, ..."`, which is
    valid Python keyword-argument syntax by construction, so it round-trips through ast
    parsing exactly. Returns None if the note isn't in that format, has no `progress` key,
    or fails to parse (e.g. a `created` / `pinned` action note uses a different format).
    """
    if not note.startswith(_CHANGED_NOTE_PREFIX):
        return None
    body = note[len(_CHANGED_NOTE_PREFIX):]
    try:
        call = ast.parse(f"f({body})", mode="eval").body
        changed = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords if kw.arg}
    except (SyntaxError, ValueError, TypeError):
        return None
    value = changed.get("progress")
    return value if isinstance(value, str) else None


def get_latest_marker(todo: Todo, marker: str) -> Optional[str]:
    """Return the most recent history entry whose new progress value starts with `marker`,
    formatted as "<timestamp> <note>", or None. Used to surface a single compact status
    line (e.g. the dev coordinator's `[dev-claim]` lock marker) without exposing full
    history via the CLI.

    Matches only entries where `marker` is the actual prefix of the progress text that was
    written, not an incidental mention elsewhere in a note's prose (e.g. a progress update
    that happens to reference "[dev-claim]" mid-sentence must not be mistaken for a real
    marker entry).
    """
    for entry in reversed(todo.history or []):
        if not entry.note:
            continue
        progress_value = _changed_progress_value(entry.note)
        if progress_value is not None and progress_value.startswith(marker):
            return f"{entry.timestamp} {entry.note}"
    return None


STATUS_ACTION = {
    "pending": "deactivated", "active": "activated",
    "awaiting": "awaiting", "completed": "completed", "deleted": "deleted",
}
UNPIN_STATUSES = {"pending", "completed", "deleted"}
LEGACY_AWAITING_FIELDS = {"awaiting", "awaiting_until"}
_RESUME_GUIDANCE = {
    "pending": "Cannot auto-resume an unstarted task; use status=active",
    "completed": "Cannot auto-resume closed work; use status=active or status=awaiting",
    "deleted": "Cannot auto-resume closed work; use status=active or status=awaiting",
}


def _legacy_awaiting_rejected(fields) -> None:
    if fields.keys() & LEGACY_AWAITING_FIELDS:
        raise ValueError(
            "awaiting and awaiting_until are no longer writable; "
            "use y todo status <id> awaiting/active or status=awaiting"
        )


def _pointer_chat(session, row, chat_id: str) -> None:
    from storage.entity.chat import ChatEntity
    if not session.query(ChatEntity.id).filter_by(
        user_id=row.user_id, chat_id=chat_id, trace_id=row.todo_id,
    ).first():
        raise ValueError("awaiting_chat must name a same-owner, same-trace chat")


def _status_side_effects(row, fields, status: str) -> None:
    if fields.get("status") == row.status:
        return
    fields["completed_at"] = get_utc_iso8601_timestamp() if status == "completed" else None
    if status != "awaiting":
        fields["awaiting_chat"] = None
    if row.pinned and "pinned" not in fields and status in UNPIN_STATUSES:
        fields["pinned"] = False


def _transition_locked(session, row, fields, *, action="updated", extra_note=None, notice=None):
    """Owner-locked status/pointer transition. Returns whether the row changed.

    `extra_note` is bounded fault evidence (watchdog/death claims only) folded
    into the same history entry as the status change, never a separate reason
    field or a synthetic agent progress message. `notice` is a writer-supplied
    awaiting summary, labelled separately so the DM's content is auditable.
    """
    fields = dict(fields)
    _legacy_awaiting_rejected(fields)
    if "status" in fields:
        status = fields["status"]
        if status not in STATUS_ACTION:
            raise ValueError("Invalid todo status")
        if status == "awaiting":
            if "awaiting_chat" not in fields:
                fields["awaiting_chat"] = None
            if notice and row.status == "awaiting":
                raise ValueError(
                    "notice is only sent when a todo newly enters awaiting; "
                    "no new notice was sent. Resume to active, then await with --note"
                )
        elif fields.get("awaiting_chat"):
            raise ValueError("awaiting_chat is only valid while status is awaiting")
        _status_side_effects(row, fields, status)
    elif "awaiting_chat" in fields and row.status != "awaiting":
        raise ValueError("awaiting_chat is only valid while status is awaiting")
    if fields.get("awaiting_chat"):
        if fields.get("status", row.status) != "awaiting":
            raise ValueError("awaiting_chat is only valid while status is awaiting")
        _pointer_chat(session, row, fields["awaiting_chat"])
    if "tags" in fields and fields["tags"] is not None:
        fields["tags"] = normalize_tags(fields["tags"])
    changed = {k: v for k, v in fields.items() if getattr(row, k) != v}
    if not changed:
        return False
    if "status" in changed:
        action = STATUS_ACTION.get(fields["status"], action)
        if row.status == "awaiting" and fields["status"] == "active":
            action = "resumed"
    for key, value in changed.items():
        setattr(row, key, value)
    note = f"changed: {', '.join(f'{k}={v!r}' for k, v in changed.items())}"
    if extra_note:
        note = f"{note}; fault: {extra_note[:FAULT_TEXT_LIMIT]}"
    if notice and "status" in changed:
        note = f"{note}; notice: {notice}"
    row.history = [*(row.history or []), TodoHistoryEntry(
        timestamp=get_utc_iso8601_timestamp(), unix_timestamp=get_unix_timestamp(),
        action=action, note=note,
    ).to_dict()]
    return True


_NOTICE_NAME_LIMIT = 120
NOTICE_LIMIT = 200
FAULT_TEXT_LIMIT = 1000
_CREDENTIAL_RES = (
    re.compile(r"(?<![A-Za-z0-9])sk-"),
    re.compile(r"(?<![A-Za-z0-9])ghp_"),
    re.compile(r"(?<![A-Za-z0-9])gho_"),
    re.compile(r"(?<![A-Za-z0-9])github_pat_"),
    re.compile(r"(?<![A-Za-z0-9])AKIA"),
    re.compile(r"(?<![A-Za-z0-9])xoxb-"),
    re.compile(r"Bearer "),
    re.compile(r"Authorization:"),
    re.compile(r"://user:pass@"),
)
_MIXED_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9+/_\-]{40,}(?![A-Za-z0-9])")
_HEX_TOKEN = re.compile(r"^[0-9a-fA-F]+$")
_HAS_LETTER = re.compile(r"[A-Za-z]")
_HAS_DIGIT = re.compile(r"[0-9]")


def _collapse_notice(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    collapsed = " ".join(str(text).split())
    return collapsed or None


def _matches_credential_shape(text: str) -> bool:
    if any(pattern.search(text) for pattern in _CREDENTIAL_RES):
        return True
    return any(
        not _HEX_TOKEN.fullmatch(token) and _HAS_LETTER.search(token) and _HAS_DIGIT.search(token)
        for token in _MIXED_TOKEN.findall(text)
    )


def validate_notice(text: Optional[str]) -> Optional[str]:
    """Collapse and accept a writer-supplied awaiting summary, or raise.

    Omitted notice stays None. An explicit empty/whitespace summary is
    rejected so the writer cannot think a blank --note was recorded.
    Over-long or credential-shaped text is rejected before any mutation so
    the writer can retry with a shorter, non-secret sentence. Truncating
    or dropping would hide the loss.
    """
    if text is None:
        return None
    collapsed = _collapse_notice(text)
    if collapsed is None:
        raise ValueError("notice must be a non-empty sentence after whitespace collapse")
    if len(collapsed) > NOTICE_LIMIT:
        raise ValueError(
            f"notice must be at most {NOTICE_LIMIT} characters after whitespace collapse; shorten and retry"
        )
    if _matches_credential_shape(collapsed):
        raise ValueError("notice matches a credential shape; omit secrets and retry")
    return collapsed


def notice_excerpt(text: Optional[str]) -> Optional[str]:
    """Bounded machine-fed excerpt, or None when it matches a credential shape.

    Watchdog/death claims cannot retry, so a matching tail is omitted rather
    than rejected. Length is still bounded by FAULT_TEXT_LIMIT.
    """
    collapsed = _collapse_notice(text)
    if collapsed is None:
        return None
    excerpt = collapsed[:FAULT_TEXT_LIMIT]
    if _matches_credential_shape(excerpt):
        return None
    return excerpt


def awaiting_notice_text(todo: Todo, extra: Optional[str] = None) -> str:
    """Plain-text owner DM for a new awaiting inbox entry.

    `extra` is bounded context from the triggering event: watchdog/death
    evidence, or a writer-supplied awaiting summary. It is never read back
    from a persisted reason field.
    """
    name = (todo.name or "")[:_NOTICE_NAME_LIMIT]
    lines = [
        f"Todo {todo.todo_id} needs you",
        name,
    ]
    if extra:
        lines.append(extra[:FAULT_TEXT_LIMIT])
    return "\n".join(lines)


def _maybe_notice(user_id: int, todo_id: str, todo: Optional[Todo], entered: bool,
                  *, extra: Optional[str] = None) -> Optional[Todo]:
    if todo and entered:
        try:
            telegram_service.send_owner_notice(user_id, awaiting_notice_text(todo, extra))
        except Exception:
            logger.exception(
                "todo awaiting notice failed: user_id={} todo_id={}", user_id, todo_id,
            )
    return todo


def _mutate_transition(user_id: int, todo_id: str, mutate) -> Tuple[Optional[Todo], bool, bool]:
    entered = False
    changed = False

    def apply(session, row):
        nonlocal entered, changed
        before = row.status
        changed = bool(mutate(session, row))
        entered = changed and before != "awaiting" and row.status == "awaiting"
        return changed

    return todo_repo.mutate_todo(user_id, todo_id, apply), entered, changed


def update_todo(user_id: int, todo_id: str, **fields) -> Optional[Todo]:
    allowed = {"name", "desc", "tags", "due_date", "priority", "progress", "status",
               "awaiting_chat", "pinned"}
    unknown = fields.keys() - allowed - LEGACY_AWAITING_FIELDS
    if unknown:
        raise ValueError("Unknown todo fields")
    _legacy_awaiting_rejected(fields)

    def apply(session, row):
        return _transition_locked(session, row, fields)

    todo, entered, _changed = _mutate_transition(user_id, todo_id, apply)
    if todo and "tags" in fields:
        tag_repo.sync_tags(user_id, "todo", todo.todo_id, todo.tags or [])
    return _maybe_notice(user_id, todo_id, todo, entered)


def pin_todo(user_id: int, todo_id: str, pinned: bool) -> Optional[Todo]:
    return todo_repo.mutate_todo(user_id, todo_id, lambda session, row: _transition_locked(
        session, row, {"pinned": pinned}, action="pinned" if pinned else "unpinned"))


def update_status(
    user_id: int, todo_id: str, status: str, chat_id: Optional[str] = None,
    notice: Optional[str] = None,
) -> Optional[Todo]:
    if status not in STATUS_ACTION:
        raise ValueError("Invalid todo status")
    if chat_id is not None and status != "awaiting":
        raise ValueError("chat_id is only valid when status is awaiting")
    if notice is not None and status != "awaiting":
        raise ValueError("notice is only valid when status is awaiting")
    summary = validate_notice(notice)

    def apply(session, row):
        if status == "awaiting":
            return _await_locked(session, row, chat_id, notice=summary)
        return _transition_locked(session, row, {"status": status})

    todo, entered, _changed = _mutate_transition(user_id, todo_id, apply)
    return _maybe_notice(user_id, todo_id, todo, entered, extra=summary)


def _await_locked(
    session, row, chat_id: Optional[str], *, extra_note: Optional[str] = None,
    notice: Optional[str] = None,
) -> bool:
    return _transition_locked(
        session, row, {"status": "awaiting", "awaiting_chat": chat_id},
        extra_note=extra_note, notice=notice,
    )


def resume_locked(session, row) -> bool:
    """Owner-locked awaiting-to-active helper for human-message auto-resume.

    Explicit status writes use `update_status` / `_transition_locked` and allow
    every source-to-target pair. Automatic resume stays awaiting-only so a
    human message cannot revive pending or closed work.
    """
    if row.status == "active":
        return False
    if row.status != "awaiting":
        raise ValueError(_RESUME_GUIDANCE.get(row.status, "Auto-resume requires an awaiting todo"))
    return _transition_locked(session, row, {"status": "active"})


def claim_fault(user_id: int, todo_id: str, *, expected_updated_at_unix: int, recheck) -> Tuple[Optional[Todo], bool]:
    """Watchdog/death fault claim: active -> awaiting under fresh under-lock evidence.

    `recheck(session, row)` re-validates the fault against the locked row and
    returns `(detail_text, pointer_chat_id)` to claim with, or `None` to abort
    without mutation. `detail_text` is bounded fault evidence folded into the
    same history entry as the status change and into the owner notice; it is
    never read back from a persisted reason field. Only an `active` row with
    the expected `updated_at_unix` is eligible, so intervening progress/status
    writes invalidate a stale claim attempt before `recheck` even runs.
    """
    claimed = {}

    def apply(session, row):
        if row.status != "active" or row.updated_at_unix != expected_updated_at_unix:
            return False
        outcome = recheck(session, row)
        if outcome is None:
            return False
        detail, pointer_chat_id = outcome
        claimed["detail"] = detail
        return _await_locked(session, row, pointer_chat_id, extra_note=detail)

    todo, entered, changed = _mutate_transition(user_id, todo_id, apply)
    return _maybe_notice(user_id, todo_id, todo, entered, extra=claimed.get("detail")), changed


def bulk_update_todos(
    user_id: int,
    todo_ids: List[str],
    *,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    pinned: Optional[bool] = None,
) -> int:
    """Apply one or more updates to a batch of todos, reusing the single-todo
    service functions so each keeps its own history semantics. Missing todo_ids
    are silently skipped. Returns the count of todos that were updated."""
    count = 0
    for todo_id in todo_ids:
        updated = False
        if status is not None:
            if update_status(user_id, todo_id, status) is not None:
                updated = True
        if priority is not None:
            if update_todo(user_id, todo_id, priority=priority) is not None:
                updated = True
        if pinned is not None:
            if pin_todo(user_id, todo_id, pinned) is not None:
                updated = True
        if updated:
            count += 1
    return count
