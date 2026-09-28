"""Per-request transcript usage: validation, attribution, ingest record, read.

Rows arrive from a scanner that already decided which of the owner's chats a
request belongs to. This service checks that claim again, stores the counters,
and reads them back per trace. It does not infer anything the transcript did
not record: cost is unavailable, and historical completeness is unknown.
"""

import re
from datetime import datetime, timedelta, timezone

from storage.repository import chat_request_usage as repo
from storage.service import user_preference as user_pref_service


INGEST_KEY = "chat_request_usage_ingest"

COUNTERS = repo.COUNTERS
MAX_ROWS = 500
MAX_BYTES = 512 * 1024
MAX_COUNTER = 10_000_000
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
CHAT_ID_RE = re.compile(r"^[0-9a-z-]{1,64}$")
TRACE_ID_RE = re.compile(r"^[^\s\]]{1,200}$")
MAX_HINTS = 200
RUN_FUTURE = timedelta(minutes=10)
REQUESTED_AT_PAST = timedelta(days=400)
REQUESTED_AT_FUTURE = timedelta(minutes=10)

RUN_COUNT_FIELDS = (
    "files_seen",
    "files_uploaded",
    "files_unmatched",
    "files_in_progress",
    "files_failed",
    "malformed_lines",
    "rows_sent",
    "rows_rejected",
    "unattributed_requests",
    "unsupported_subagent_requests",
)
# files_unmatched is expected: personal interactive sessions never match.
# Everything else besides the two plain volume counts is an exception.
CLEAN_IGNORED = {"files_seen", "files_uploaded", "rows_sent", "files_unmatched"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _reason(row_index: int, reason: str) -> dict:
    return {"index": row_index, "reason": reason}


def _printable(value: str) -> bool:
    return all(ch.isprintable() and ch not in "\r\n\t" for ch in value)


def _counter(value):
    """Return the integer, or None when the value is not a legal counter.

    A bool is an int in Python and is rejected on purpose. So is anything that
    is not a finite integer inside the closed range.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > MAX_COUNTER:
        return None
    return value


def _requested_at(value: str, now: datetime):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    if not (now - REQUESTED_AT_PAST <= parsed <= now + REQUESTED_AT_FUTURE):
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _trace_id_ok(value) -> bool:
    return isinstance(value, str) and bool(TRACE_ID_RE.fullmatch(value)) and _printable(value)


def validate_sessions(sessions) -> list[dict]:
    """Check a resolve payload's shape. Raises ValueError naming the bad field.

    Everything that reaches the database lookup is a bounded string of the
    same character set the upload accepts, so a malformed nested value is a
    422, not an exception deep inside the query.
    """
    if not isinstance(sessions, list):
        raise ValueError("sessions must be a list")
    clean = []
    for index, session in enumerate(sessions):
        if not isinstance(session, dict):
            raise ValueError(f"sessions[{index}] must be an object")
        session_id = session.get("session_id")
        if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
            raise ValueError(f"sessions[{index}].session_id")
        hints = session.get("hints")
        if hints is None:
            hints = []
        if not isinstance(hints, list) or len(hints) > MAX_HINTS:
            raise ValueError(f"sessions[{index}].hints")
        clean_hints = []
        for position, hint in enumerate(hints):
            where = f"sessions[{index}].hints[{position}]"
            if not isinstance(hint, dict):
                raise ValueError(f"{where} must be an object")
            chat_id = hint.get("chat_id")
            if not isinstance(chat_id, str) or not CHAT_ID_RE.fullmatch(chat_id):
                raise ValueError(f"{where}.chat_id")
            trace_id = hint.get("trace_id")
            if trace_id is not None and not _trace_id_ok(trace_id):
                raise ValueError(f"{where}.trace_id")
            clean_hints.append({"chat_id": chat_id, "trace_id": trace_id})
        clean.append({"session_id": session_id, "hints": clean_hints})
    return clean


def validate_row(row: dict, index: int, now: datetime | None = None):
    """Check one uploaded row. Returns (clean_row, None) or (None, rejection)."""
    now = now or _now()
    if not isinstance(row, dict):
        return None, _reason(index, "not_an_object")

    request_id = row.get("request_id")
    if not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id):
        return None, _reason(index, "request_id")
    session_id = row.get("session_id")
    if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
        return None, _reason(index, "session_id")
    chat_id = row.get("chat_id")
    if not isinstance(chat_id, str) or not CHAT_ID_RE.fullmatch(chat_id):
        return None, _reason(index, "chat_id")
    model = row.get("model")
    if not isinstance(model, str) or not model or len(model) > 200 or not _printable(model):
        return None, _reason(index, "model")
    requested_at = _requested_at(row.get("requested_at"), now)
    if requested_at is None:
        return None, _reason(index, "requested_at")
    attribution = row.get("attribution")
    if attribution not in ("hint", "session"):
        return None, _reason(index, "attribution")
    trace_id = row.get("trace_id")
    if attribution == "hint" and not (trace_id is None or _trace_id_ok(trace_id)):
        return None, _reason(index, "trace_id")

    usage = row.get("usage")
    clean = {
        "request_id": request_id,
        "session_id": session_id,
        "chat_id": chat_id,
        "model": model,
        "requested_at": requested_at,
        "attribution": attribution,
        "trace_id": trace_id if attribution == "hint" else None,
    }
    if not isinstance(usage, dict) or not any(name in usage for name in COUNTERS):
        clean["usage_state"] = "missing"
        for name in COUNTERS:
            clean[name] = None
        return clean, None

    for name in COUNTERS:
        if name not in usage or usage[name] is None:
            clean[name] = None
            continue
        value = _counter(usage[name])
        if value is None:
            return None, _reason(index, name)
        clean[name] = value
    clean["usage_state"] = "observed"
    return clean, None


def validate_rows(rows: list, now: datetime | None = None) -> dict:
    """Split a batch into accepted rows and per-row rejections.

    One bad row does not reject its neighbours. The size limits are the
    caller's to enforce before this runs.
    """
    accepted = []
    rejected = []
    for index, row in enumerate(rows):
        clean, rejection = validate_row(row, index, now)
        if rejection is not None:
            rejected.append(rejection)
        else:
            clean["index"] = index
            accepted.append(clean)
    return {"accepted": accepted, "rejected": rejected}


def _chat_lookup(user_id: int, chat_ids: list[str]) -> dict[str, dict]:
    """Owner chats keyed by public chat id, with the fields attribution needs."""
    from storage.database.base import get_db
    from storage.entity.chat import ChatEntity

    if not chat_ids:
        return {}
    with get_db() as session:
        found = session.query(ChatEntity).filter(
            ChatEntity.user_id == user_id,
            ChatEntity.chat_id.in_(chat_ids),
        ).all()
    return {
        row.chat_id: {
            "backend": row.backend or "",
            "trace_id": row.trace_id or "",
            "routine_id": row.routine_id or "",
            "external_id": row.external_id or "",
        }
        for row in found
    }


def _hint_chat(chat: dict | None, hint: dict) -> str | None:
    """Why a hint does not identify this owner's chat, or None when it does."""
    if chat is None:
        return "not_owner_chat"
    if chat["backend"] != "claude_code":
        return "backend_not_claude_code"
    # A routine hint carries no trace. It is valid for the owner's claude_code
    # chat that belongs to a routine, whether or not that chat also has a trace.
    if hint.get("trace_id") is None:
        return None if chat["routine_id"] else "routine_required"
    if chat["trace_id"] != hint["trace_id"]:
        return "trace_mismatch"
    return None


def resolve_sessions(user_id: int, sessions: list[dict]) -> dict:
    """Validate attribution hints and resolve the session-level chat.

    A hint counts only for the owner's own claude_code chat whose trace matches
    the hint. A routine hint (trace_id null) additionally needs a chat that
    belongs to a routine. The session-level chat is the owner's chat whose
    external_id is the session id, when there is one. Nothing here writes.
    Raises ValueError for a payload validate_sessions refuses.
    """
    sessions = validate_sessions(sessions)
    chat_ids = []
    for session in sessions:
        for hint in session.get("hints") or []:
            chat_id = hint.get("chat_id")
            if isinstance(chat_id, str):
                chat_ids.append(chat_id)
    chats = _chat_lookup(user_id, chat_ids)
    external = _external_sessions(user_id, [s.get("session_id") for s in sessions])

    resolved = []
    for session in sessions:
        hints = []
        for hint in session.get("hints") or []:
            chat_id = hint.get("chat_id")
            reason = _hint_chat(chats.get(chat_id), hint)
            hints.append({
                "chat_id": chat_id,
                "trace_id": hint.get("trace_id"),
                "valid": reason is None,
                "reason": reason,
            })
        session_id = session.get("session_id")
        resolved.append({
            "session_id": session_id,
            "session_chat_id": external.get(session_id),
            "hints": hints,
        })
    return {"sessions": resolved}


def _external_sessions(user_id: int, session_ids: list) -> dict[str, str]:
    """Map a session id to the owner's claude_code chat whose external_id
    equals it. Upload accepts no other backend, so resolve offers none."""
    from storage.database.base import get_db
    from storage.entity.chat import ChatEntity

    wanted = [s for s in session_ids if isinstance(s, str) and s]
    if not wanted:
        return {}
    with get_db() as session:
        rows = session.query(ChatEntity.external_id, ChatEntity.chat_id).filter(
            ChatEntity.user_id == user_id,
            ChatEntity.backend == "claude_code",
            ChatEntity.external_id.in_(wanted),
        ).all()
    return {row.external_id: row.chat_id for row in rows}


def _row_accepted(chat: dict | None, row: dict) -> bool:
    """Whether this row's attribution is one resolve would have validated.

    A row says how it was attributed, and that claim is checked the same way as
    a hint. `session` requires the owner's claude_code chat whose external id is
    this session. `hint` requires the same chat, trace and routine facts a hint
    needs. Merely belonging to some trace is not enough, and a chat whose
    external id has since changed still accepts the hint it was resolved under.
    """
    if chat is None or chat["backend"] != "claude_code":
        return False
    if row.get("attribution") == "session":
        return bool(chat["external_id"]) and chat["external_id"] == row["session_id"]
    if row.get("attribution") == "hint":
        return _hint_chat(chat, {"chat_id": row["chat_id"], "trace_id": row.get("trace_id")}) is None
    return False


def store_rows(user_id: int, rows: list[dict]) -> dict:
    """Validate, drop rows whose attribution does not check out, upsert the rest."""
    checked = validate_rows(rows)
    chats = _chat_lookup(user_id, [row["chat_id"] for row in checked["accepted"]])
    kept = []
    for row in checked["accepted"]:
        if _row_accepted(chats.get(row["chat_id"]), row):
            kept.append(row)
        else:
            checked["rejected"].append(_reason(row["index"], "chat_not_resolved"))
    for row in kept:
        # Attribution was checked above. It is not a column.
        for key in ("index", "attribution", "trace_id"):
            row.pop(key, None)
    stored = repo.upsert_rows(user_id, kept)
    return {
        "accepted": stored["accepted"],
        "rejected": checked["rejected"],
        "conflicts": stored["conflicts"],
    }


def _nonneg_int(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(field)
    return value


def _run_time(value, field: str) -> datetime:
    """A timezone-aware ISO timestamp, normalized to UTC. Anything else is refused,
    so a stored run can always be compared with the current time."""
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValueError(field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(field) from exc
    if parsed.tzinfo is None:
        raise ValueError(field)
    return parsed.astimezone(timezone.utc)


def _parse_aware(value) -> datetime | None:
    """A stored timestamp, or None when it is missing, malformed or naive."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def record_run(user_id: int, run: dict) -> dict:
    """Store one scanner run as this user's latest run for its host.

    Outcome is `clean` only when every exception counter is zero.
    files_unmatched does not spoil a run: personal sessions are expected to
    stay unmatched. The record keeps the counts either way.
    """
    host = run.get("host")
    if not isinstance(host, str) or not host or len(host) > 200:
        raise ValueError("host")
    counts = {field: _nonneg_int(run.get(field, 0), field) for field in RUN_COUNT_FIELDS}
    conflicts = run.get("conflicts") or {}
    if not isinstance(conflicts, dict):
        raise ValueError("conflicts")
    unknown = set(conflicts) - {"session", "chat", "model"}
    if unknown:
        raise ValueError(f"conflicts.{sorted(unknown)[0]}")
    started_at = _run_time(run.get("started_at"), "started_at")
    finished_at = _run_time(run.get("finished_at"), "finished_at")
    if started_at > finished_at:
        raise ValueError("started_at after finished_at")
    if finished_at > _now() + RUN_FUTURE:
        raise ValueError("finished_at in the future")
    counts["conflicts"] = {
        "session": _nonneg_int(conflicts.get("session", 0), "conflicts.session"),
        "chat": _nonneg_int(conflicts.get("chat", 0), "conflicts.chat"),
        "model": _nonneg_int(conflicts.get("model", 0), "conflicts.model"),
    }
    spoiled = [
        field for field in RUN_COUNT_FIELDS
        if field not in CLEAN_IGNORED and counts[field]
    ]
    if any(counts["conflicts"].values()):
        spoiled.append("conflicts")
    counts["outcome"] = "clean" if not spoiled else "completed_with_exceptions"
    counts["started_at"] = started_at.isoformat()
    counts["finished_at"] = finished_at.isoformat()

    current = user_pref_service.get_preference(user_id, INGEST_KEY)
    stored = dict(current.value) if current is not None and isinstance(current.value, dict) else {}
    latest = dict(stored.get("latest_run") or {})
    latest[host] = counts
    stored["latest_run"] = latest
    user_pref_service.upsert_preference(user_id, INGEST_KEY, stored)
    return counts


def latest_run(user_id: int) -> dict | None:
    """The most recently finished run across hosts, or None when none exists."""
    current = user_pref_service.get_preference(user_id, INGEST_KEY)
    if current is None or not isinstance(current.value, dict):
        return None
    runs = [run for run in (current.value.get("latest_run") or {}).values() if isinstance(run, dict)]
    # A record without a usable timezone-aware finish time cannot be ordered
    # against the others, so it is ignored rather than allowed to raise.
    finished = [(when, run) for run in runs if (when := _parse_aware(run.get("finished_at")))]
    if not finished:
        return None
    return max(finished, key=lambda pair: pair[0])[1]


def _sum(rows: list, counter: str) -> tuple[int, int]:
    """(sum of present values, count of rows whose value is NULL)."""
    present = [getattr(row, counter) for row in rows if getattr(row, counter) is not None]
    return sum(present), len(rows) - len(present)


def _counter_block(rows: list) -> dict:
    block = {"requests_observed": len(rows), "missing_requests": {}}
    for counter in COUNTERS:
        total, missing = _sum(rows, counter)
        block[counter] = total
        block["missing_requests"][counter] = missing
    return block


def _inbound(json_content: str) -> int:
    """User-role messages in a chat body. A body that does not parse counts 0."""
    import json

    try:
        payload = json.loads(json_content or "")
    except (ValueError, TypeError):
        return 0
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list):
        return 0
    return sum(1 for message in messages if isinstance(message, dict) and message.get("role") == "user")


def aggregate_for_trace(user_id: int, trace_id: str, now: datetime | None = None) -> dict:
    """Totals, per model and per chat for one trace, plus scan freshness.

    `sessions` counts chats on the trace. `transcripts` counts distinct session
    ids in the uploaded rows. `turns` comes from the derived activity table and
    `inbound` from the chat body. A chat that is not claude_code reports
    collected: false instead of a zero that would look like a scanned session.
    """
    from storage.database.base import get_db
    from storage.entity.chat import ChatEntity

    now = now or _now()
    with get_db() as session:
        chats = session.query(ChatEntity).filter(
            ChatEntity.user_id == user_id,
            ChatEntity.trace_id == trace_id,
        ).order_by(ChatEntity.created_at_unix.asc()).all()

    chat_ids = [chat.chat_id for chat in chats]
    rows = repo.rows_for_chats(user_id, chat_ids)
    turns = repo.turns_for_chats(user_id, chat_ids)
    by_chat: dict[str, list] = {}
    for row in rows:
        by_chat.setdefault(row.chat_id, []).append(row)

    per_chat = []
    for chat in chats:
        entry = {
            "chat_id": chat.chat_id,
            "skill": chat.skill or "",
            "bot_name": chat.bot_name or "",
            "tier": chat.tier or "",
            "backend": chat.backend or "",
            "created_at_unix": chat.created_at_unix or 0,
            "turns": turns.get(chat.chat_id, 0),
            "inbound": _inbound(chat.json_content),
        }
        if (chat.backend or "") != "claude_code":
            entry["collected"] = False
            entry["reason"] = "backend_not_claude_code"
            entry["requests_observed"] = 0
        else:
            entry["collected"] = True
            entry.update(_counter_block(by_chat.get(chat.chat_id, [])))
        per_chat.append(entry)

    by_model: dict[str, list] = {}
    for row in rows:
        by_model.setdefault(row.model, []).append(row)
    per_model = [
        {"model": model, **_counter_block(model_rows)}
        for model, model_rows in sorted(by_model.items())
    ]

    return {
        "trace_id": trace_id,
        "sessions": len(chats),
        "transcripts": len({row.session_id for row in rows}),
        "requests": len(rows),
        "turns": sum(turns.get(chat.chat_id, 0) for chat in chats),
        "inbound": sum(entry["inbound"] for entry in per_chat),
        "tokens": _counter_block(rows),
        "models": per_model,
        "chats": per_chat,
        "collection": _collection(user_id, now),
        "historical_completeness": "unknown",
        "cost": {"status": "unavailable", "reason": "no_recorded_per_request_cost"},
    }


def _collection(user_id: int, now: datetime) -> dict:
    """Scan freshness. No run on record is its own state, not a zero."""
    run = latest_run(user_id)
    if run is None:
        return {"state": "never_run"}
    finished = run.get("finished_at")
    parsed = _parse_aware(finished)
    age = max(0, int((now - parsed).total_seconds())) if parsed else None
    disclosures = {
        field: run.get(field, 0)
        for field in (
            "files_unmatched", "files_in_progress", "files_failed",
            "malformed_lines", "rows_rejected", "unattributed_requests",
            "unsupported_subagent_requests",
        )
    }
    disclosures["conflicts"] = run.get("conflicts") or {"session": 0, "chat": 0, "model": 0}
    return {
        "latest_scan_finished_at": finished,
        "scan_age_seconds": age,
        "outcome": run.get("outcome"),
        "disclosures": disclosures,
    }
