"""Session context analysis: strict ingest validation, unit replacement, read.

A unit is what the VM analysed for one of the owner's chats in one transcript
session (todo 3844). The upload is checked field by field against a closed
schema: an unrecognised key anywhere is refused, so no field can carry a
prompt, output, tool body or secret. Labels are the only free-form strings;
one that is not a short relative name is dropped to NULL and counted, never
stored. Attribution is re-checked exactly like a 3729 usage row.

Everything derived from the counters (prompt size P = U + W + R, growth, the
input-only cache reuse R / P, the unknown residual, session totals) is
computed here, never accepted from the client. NULL is not zero: a missing
counter makes P, growth and the ratio NULL. Cost stays unavailable and
historical completeness unknown. Reads use stored rows only.
"""

import re
from datetime import datetime, timedelta, timezone

from storage.repository import chat_context as repo
from storage.service import chat_request_usage as usage_service


CATEGORIES = (
    "system_prompt", "rules_memory", "skills_references", "tool_schemas",
    "file_results", "tool_results", "conversation",
)
COUNTERS = usage_service.COUNTERS
TOKEN_METHODS = {"utf8_bytes_div_4_v1"}
UNIT_STATES = {"analyzed", "partial", "unsupported"}
REQUEST_STATES = {"analyzed", "partial"}
REQUEST_GAPS = {"broken_chain", "compaction_preserved_segment", "no_prompt_snapshot", "no_tool_snapshot"}
SUGGESTION_KINDS = {"repeated_identical_read", "large_tool_result", "heavy_startup", "prefix_change"}
ORIGINS = {
    "instructions", "instructions_rendering", "nested_memory", "skill_listing", "skill_result",
    "skill_body", "deferred_tools_delta", "system_prompt", "tool_schema", "tool_result",
    "file_read", "rules_read", "reference_read", "user_text", "meta_text", "assistant_text",
    "thinking", "tool_input", "compact_summary",
}

MAX_BODY_BYTES = 1024 * 1024
MAX_REQUESTS = 600
MAX_CONTRIBUTORS = 200
MAX_EVENTS = 50
MAX_SUGGESTIONS = 50
MAX_CLI_VERSIONS = 10
MAX_SIZE = 2_000_000_000
DETAIL_DAYS = 30
MAX_PAGE = 200
TOP_CONTRIBUTORS = 10

OCCURRENCE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{16}$")
ORIGIN_ATTACHMENT_RE = re.compile(r"^attachment:[a-z0-9_]{1,48}$")
VERSION_RE = re.compile(r"^[0-9A-Za-z.+-]{1,32}$")
TRIGGER_RE = re.compile(r"^[a-z_]{1,32}$")
LABEL_RE = re.compile(r"^[A-Za-z0-9_.@+:/-]{1,160}$")
# A label is a relative name, never a value: drop anything shaped like a key
# or token, or any long unbroken run that could hide one.
SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{12,}|xox[abposr]-"
    r"|[A-Za-z0-9+=_-]{40,})"
)


class ContextConflict(Exception):
    """The unit was refused as a whole; `detail` names why (HTTP 409)."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class ContextTooLarge(Exception):
    """A list is over its bound (HTTP 413)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _keys(value, allowed: set, required: set, where: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{where}.{sorted(unknown)[0]}")
    missing = required - set(value)
    if missing:
        raise ValueError(f"{where}.{sorted(missing)[0]} missing")
    return value


def _int(value, where: str, low: int = 0, high: int = MAX_SIZE, nullable: bool = False):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(where)
    return value


def _bool(value, where: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(where)
    return value


def _list(value, where: str, bound: int) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{where} must be a list")
    if len(value) > bound:
        raise ContextTooLarge(f"{where} over {bound}")
    return value


class _Labels:
    """Drops unsafe labels to None and counts them."""

    def __init__(self):
        self.dropped = 0

    def __call__(self, value, where: str):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(where)
        safe = (
            LABEL_RE.fullmatch(value)
            and not value.startswith(("/", "~"))
            and ".." not in value.split("/")
            and not SECRET_RE.search(value)
        )
        if not safe:
            self.dropped += 1
            return None
        return value


def _usage(value, where: str) -> dict:
    if value is None:
        return {name: None for name in COUNTERS}
    _keys(value, set(COUNTERS), set(), where)
    return {
        name: _int(value.get(name), f"{where}.{name}", high=usage_service.MAX_COUNTER, nullable=True)
        for name in COUNTERS
    }


def _categories(value, where: str) -> dict:
    _keys(value, set(CATEGORIES), set(CATEGORIES), where)
    out = {}
    for name in CATEGORIES:
        item = _keys(value[name], {"bytes", "estimated_tokens", "complete"},
                     {"bytes", "estimated_tokens", "complete"}, f"{where}.{name}")
        out[name] = {
            "bytes": _int(item["bytes"], f"{where}.{name}.bytes", nullable=True),
            "estimated_tokens": _int(item["estimated_tokens"], f"{where}.{name}.estimated_tokens",
                                     nullable=True),
            "complete": _bool(item["complete"], f"{where}.{name}.complete"),
        }
    return out


def _request(value, index: int) -> dict:
    where = f"requests[{index}]"
    fields = {"request_id", "sequence", "epoch", "model", "requested_at", "usage", "categories",
              "unknown_overhead", "gaps", "state"}
    _keys(value, fields, fields, where)
    request_id = value["request_id"]
    if not isinstance(request_id, str) or not usage_service.REQUEST_ID_RE.fullmatch(request_id):
        raise ValueError(f"{where}.request_id")
    model = value["model"]
    if not isinstance(model, str) or len(model) > 200 or not usage_service._printable(model):
        raise ValueError(f"{where}.model")
    requested_at = value["requested_at"]
    if requested_at in (None, ""):
        requested_at = None
    else:
        requested_at = usage_service._requested_at(requested_at, _now())
        if requested_at is None:
            raise ValueError(f"{where}.requested_at")
    overhead = _keys(value["unknown_overhead"], {"opaque_reasoning_blocks", "images", "hidden_formatting"},
                     {"opaque_reasoning_blocks", "images", "hidden_formatting"}, f"{where}.unknown_overhead")
    gaps = _list(value["gaps"], f"{where}.gaps", len(REQUEST_GAPS))
    if not all(gap in REQUEST_GAPS for gap in gaps) or len(set(gaps)) != len(gaps):
        raise ValueError(f"{where}.gaps")
    if value["state"] not in REQUEST_STATES:
        raise ValueError(f"{where}.state")
    usage = _usage(value["usage"], f"{where}.usage")
    return {
        "request_id": request_id,
        "sequence": _int(value["sequence"], f"{where}.sequence", low=1),
        "epoch": _int(value["epoch"], f"{where}.epoch"),
        "model": model,
        "requested_at": requested_at,
        **usage,
        "categories": _categories(value["categories"], f"{where}.categories"),
        "unknown_overhead": {
            "opaque_reasoning_blocks": _int(overhead["opaque_reasoning_blocks"],
                                            f"{where}.unknown_overhead.opaque_reasoning_blocks"),
            "images": _int(overhead["images"], f"{where}.unknown_overhead.images"),
            "hidden_formatting": _bool(overhead["hidden_formatting"],
                                       f"{where}.unknown_overhead.hidden_formatting"),
        },
        "gaps": list(gaps),
        "state": value["state"],
    }


def _origin(value, where: str) -> str:
    if isinstance(value, str) and (value in ORIGINS or ORIGIN_ATTACHMENT_RE.fullmatch(value)):
        return value
    raise ValueError(where)


def _contributor(value, index: int, label) -> dict:
    where = f"contributors[{index}]"
    fields = {"occurrence_id", "category", "origin", "label", "digest", "bytes",
              "introduced_request", "exposure_requests"}
    _keys(value, fields, fields - {"label", "digest"}, where)
    occurrence = value["occurrence_id"]
    if not isinstance(occurrence, str) or not OCCURRENCE_RE.fullmatch(occurrence):
        raise ValueError(f"{where}.occurrence_id")
    if value["category"] not in CATEGORIES:
        raise ValueError(f"{where}.category")
    digest = value.get("digest")
    if digest is not None and (not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest)):
        raise ValueError(f"{where}.digest")
    return {
        "occurrence_id": occurrence,
        "category": value["category"],
        "origin": _origin(value["origin"], f"{where}.origin"),
        "label": label(value.get("label"), f"{where}.label"),
        "digest": digest,
        "bytes": _int(value["bytes"], f"{where}.bytes"),
        "introduced_request": _int(value["introduced_request"], f"{where}.introduced_request", low=1),
        "exposure_requests": _int(value["exposure_requests"], f"{where}.exposure_requests", low=1),
    }


def _suggestion(value, index: int, label) -> dict:
    where = f"suggestions[{index}]"
    fields = {"kind", "label", "occurrences", "bytes", "introduced_request", "estimated_tokens", "requests"}
    _keys(value, fields, {"kind"}, where)
    if value["kind"] not in SUGGESTION_KINDS:
        raise ValueError(f"{where}.kind")
    out = {"kind": value["kind"]}
    if "label" in value:
        out["label"] = label(value["label"], f"{where}.label")
    for name in ("occurrences", "bytes", "introduced_request", "estimated_tokens"):
        if name in value:
            out[name] = _int(value[name], f"{where}.{name}", nullable=True)
    if "requests" in value:
        out["requests"] = [
            _int(item, f"{where}.requests", low=1)
            for item in _list(value["requests"], f"{where}.requests", MAX_REQUESTS)
        ]
    return out


def _event(value, index: int) -> dict:
    where = f"events[{index}]"
    fields = {"kind", "epoch", "trigger", "pre_tokens", "post_tokens", "before_request", "preserved_segment"}
    _keys(value, fields, {"kind", "epoch", "before_request", "preserved_segment"}, where)
    if value["kind"] != "compaction":
        raise ValueError(f"{where}.kind")
    trigger = value.get("trigger")
    if trigger is not None and (not isinstance(trigger, str) or not TRIGGER_RE.fullmatch(trigger)):
        raise ValueError(f"{where}.trigger")
    return {
        "kind": "compaction",
        "epoch": _int(value["epoch"], f"{where}.epoch", low=1),
        "trigger": trigger,
        "pre_tokens": _int(value.get("pre_tokens"), f"{where}.pre_tokens", nullable=True),
        "post_tokens": _int(value.get("post_tokens"), f"{where}.post_tokens", nullable=True),
        "before_request": _int(value["before_request"], f"{where}.before_request", low=1),
        "preserved_segment": _bool(value["preserved_segment"], f"{where}.preserved_segment"),
    }


def _file_gaps(value) -> dict:
    fields = {"malformed_lines", "in_progress", "sidechain_records", "duplicate_records", "unreadable"}
    _keys(value, fields, set(), "gaps")
    out = {}
    for name in ("malformed_lines", "sidechain_records", "duplicate_records"):
        if name in value:
            out[name] = _int(value[name], f"gaps.{name}")
    for name in ("in_progress", "unreadable"):
        if name in value:
            out[name] = _bool(value[name], f"gaps.{name}")
    return out


UNIT_FIELDS = {
    "session_id", "chat_id", "attribution", "trace_id", "analyzer_version", "token_method", "state",
    "cli_versions", "gaps", "events", "requests", "contributors", "suggestions",
    "requests_omitted", "contributors_omitted",
}


def validate_unit(payload) -> tuple[dict, list[dict], list[dict], int]:
    """(unit, requests, contributors, labels_dropped). Raises on anything off-schema.

    Bounds raise ContextTooLarge before the items are inspected.
    """
    _keys(payload, UNIT_FIELDS, UNIT_FIELDS - {"trace_id"}, "body")
    for name, bound in (("requests", MAX_REQUESTS), ("contributors", MAX_CONTRIBUTORS),
                        ("events", MAX_EVENTS), ("suggestions", MAX_SUGGESTIONS),
                        ("cli_versions", MAX_CLI_VERSIONS)):
        _list(payload[name], name, bound)

    session_id = payload["session_id"]
    if not isinstance(session_id, str) or not usage_service.SESSION_ID_RE.fullmatch(session_id):
        raise ValueError("session_id")
    chat_id = payload["chat_id"]
    if not isinstance(chat_id, str) or not usage_service.CHAT_ID_RE.fullmatch(chat_id):
        raise ValueError("chat_id")
    if payload["attribution"] not in ("hint", "session"):
        raise ValueError("attribution")
    trace_id = payload.get("trace_id")
    if trace_id is not None and not usage_service._trace_id_ok(trace_id):
        raise ValueError("trace_id")
    if payload["token_method"] not in TOKEN_METHODS:
        raise ValueError("token_method")
    if payload["state"] not in UNIT_STATES:
        raise ValueError("state")
    for version in payload["cli_versions"]:
        if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
            raise ValueError("cli_versions")

    label = _Labels()
    requests = [_request(item, index) for index, item in enumerate(payload["requests"])]
    if len({r["request_id"] for r in requests}) != len(requests):
        raise ValueError("requests.request_id duplicate")
    if len({r["sequence"] for r in requests}) != len(requests):
        raise ValueError("requests.sequence duplicate")
    requests.sort(key=lambda r: r["sequence"])
    contributors = [_contributor(item, index, label) for index, item in enumerate(payload["contributors"])]
    if len({c["occurrence_id"] for c in contributors}) != len(contributors):
        raise ValueError("contributors.occurrence_id duplicate")
    unit = {
        "session_id": session_id,
        "chat_id": chat_id,
        "attribution": payload["attribution"],
        "trace_id": trace_id if payload["attribution"] == "hint" else None,
        "analyzer_version": _int(payload["analyzer_version"], "analyzer_version", low=1, high=10_000),
        "token_method": payload["token_method"],
        "state": payload["state"],
        "cli_versions": sorted(set(payload["cli_versions"])),
        "gaps": _file_gaps(payload["gaps"]),
        "events": [_event(item, index) for index, item in enumerate(payload["events"])],
        "suggestions": [_suggestion(item, index, label) for index, item in enumerate(payload["suggestions"])],
        "requests_omitted": _int(payload["requests_omitted"], "requests_omitted"),
        "contributors_omitted": _int(payload["contributors_omitted"], "contributors_omitted"),
    }
    return unit, requests, contributors, label.dropped


def _prompt(row) -> int | None:
    """P = U + W + R, only when all three are known. Output never takes part."""
    parts = (_get(row, "input_tokens"), _get(row, "cache_creation_tokens"), _get(row, "cache_read_tokens"))
    return sum(parts) if all(part is not None for part in parts) else None


def _get(row, name):
    return row[name] if isinstance(row, dict) else getattr(row, name)


def summarize(requests: list) -> dict:
    """Occupancy (startup / peak / latest P) apart from cumulative input sum(P)."""
    known = [(row, prompt) for row in requests if (prompt := _prompt(row)) is not None]
    prompts = [prompt for _row, prompt in known]
    return {
        "requests": len(requests),
        "requests_with_prompt": len(known),
        "startup_prompt_tokens": prompts[0] if prompts else None,
        "peak_prompt_tokens": max(prompts) if prompts else None,
        "latest_prompt_tokens": prompts[-1] if prompts else None,
        "cumulative_input_tokens": sum(prompts) if prompts else None,
        "cumulative_cache_read_tokens": sum(_get(row, "cache_read_tokens") for row, _p in known) if known else None,
    }


def store_unit(user_id: int, payload, now: datetime | None = None) -> dict:
    """Validate, re-check attribution, replace the unit, purge expired detail.

    Raises ValueError (422), ContextTooLarge (413) or ContextConflict (409).
    `now` stamps the analysis; validation always uses the real clock.
    """
    unit, requests, contributors, dropped = validate_unit(payload)
    chats = usage_service._chat_lookup(user_id, [unit["chat_id"]])
    claim = {"chat_id": unit["chat_id"], "session_id": unit["session_id"],
             "attribution": unit["attribution"], "trace_id": unit["trace_id"]}
    if not usage_service._row_accepted(chats.get(unit["chat_id"]), claim):
        raise ValueError("chat_not_resolved")

    now = now or _now()
    record = {key: unit[key] for key in unit if key not in ("attribution", "trace_id")}
    record.update(summarize(requests))
    stamps = [r["requested_at"] for r in requests if r["requested_at"]]
    record["started_at"] = min(stamps) if stamps else None
    record["labels_dropped"] = dropped
    record["analyzed_at"] = now.isoformat()
    record["analyzed_at_unix"] = int(now.timestamp())
    cutoff = int((_now() - timedelta(days=DETAIL_DAYS)).timestamp())
    outcome = repo.replace_unit(user_id, record, requests, contributors, cutoff)
    if outcome != "replaced":
        raise ContextConflict(outcome)
    return {
        "accepted_requests": len(requests),
        "contributors": len(contributors),
        "labels_dropped": dropped,
        "state": unit["state"],
    }


def _request_view(row, previous) -> dict:
    usage = {name: getattr(row, name) for name in COUNTERS}
    prompt = _prompt(row)
    prior = _prompt(previous) if previous is not None else None
    same = previous is not None and previous.session_id == row.session_id and previous.epoch == row.epoch
    known = sum(item.get("estimated_tokens") or 0 for item in (row.categories or {}).values())
    residual = prompt - known if prompt is not None else None
    return {
        "request_id": row.request_id,
        "session_id": row.session_id,
        "sequence": row.sequence,
        "epoch": row.epoch,
        "model": row.model,
        "requested_at": row.requested_at,
        "usage": usage,
        "prompt_tokens": prompt,
        "growth": prompt - prior if same and prompt is not None and prior is not None else None,
        "cache_reuse": usage["cache_read_tokens"] / prompt if prompt else None,
        "categories": row.categories,
        "unknown_tokens_estimate": residual if residual is not None and residual >= 0 else None,
        "estimate_exceeds_observed": residual is not None and residual < 0,
        "unknown_overhead": row.unknown_overhead,
        "gaps": row.gaps,
        "state": row.state,
    }


def _contributor_view(row) -> dict:
    return {
        "session_id": row.session_id,
        "category": row.category,
        "origin": row.origin,
        "label": row.label,
        "digest": row.digest,
        "bytes": row.bytes,
        "estimated_tokens": (row.bytes + 3) // 4,
        "introduced_request": row.introduced_request,
        "exposure_requests": row.exposure_requests,
        "estimated_exposure_bytes": row.bytes * row.exposure_requests,
    }


def _unit_view(unit, cutoff_unix: int) -> dict:
    return {
        "session_id": unit.session_id,
        "analyzer_version": unit.analyzer_version,
        "token_method": unit.token_method,
        "state": unit.state,
        "cli_versions": unit.cli_versions,
        "gaps": unit.gaps,
        "events": unit.events,
        "suggestions": unit.suggestions,
        "summary": _unit_summary(unit),
        "requests_omitted": unit.requests_omitted,
        "contributors_omitted": unit.contributors_omitted,
        "labels_dropped": unit.labels_dropped,
        "analyzed_at": unit.analyzed_at,
        "detail_expired": unit.analyzed_at_unix < cutoff_unix,
    }


def _unit_summary(unit) -> dict:
    return {
        "requests": unit.requests,
        "requests_with_prompt": unit.requests_with_prompt,
        "startup_prompt_tokens": unit.startup_prompt_tokens,
        "peak_prompt_tokens": unit.peak_prompt_tokens,
        "latest_prompt_tokens": unit.latest_prompt_tokens,
        "cumulative_input_tokens": unit.cumulative_input_tokens,
        "cache_reuse": _ratio(unit.cumulative_cache_read_tokens, unit.cumulative_input_tokens),
    }


def _ratio(part, whole):
    return part / whole if part is not None and whole else None


def _chat_summary(units: list) -> dict | None:
    """The chat across its units: occupancy from the first / largest / last unit,
    cumulative input and cache reuse over requests with all counters known."""
    if not units:
        return None
    priced = [u for u in units if u.cumulative_input_tokens is not None]
    peaks = [u.peak_prompt_tokens for u in units if u.peak_prompt_tokens is not None]
    starts = [u.startup_prompt_tokens for u in units if u.startup_prompt_tokens is not None]
    latest = [u.latest_prompt_tokens for u in units if u.latest_prompt_tokens is not None]
    total = sum(u.cumulative_input_tokens for u in priced) if priced else None
    read = sum(u.cumulative_cache_read_tokens or 0 for u in priced) if priced else None
    return {
        "requests": sum(u.requests for u in units),
        "requests_with_prompt": sum(u.requests_with_prompt for u in units),
        "startup_prompt_tokens": starts[0] if starts else None,
        "peak_prompt_tokens": max(peaks) if peaks else None,
        "latest_prompt_tokens": latest[-1] if latest else None,
        "cumulative_input_tokens": total,
        "cache_reuse": _ratio(read, total),
    }


def _chat_state(units: list) -> str:
    states = {u.state for u in units}
    if states == {"unsupported"}:
        return "unsupported"
    return "partial" if states - {"analyzed"} else "analyzed"


def _owned_chat(user_id: int, chat_id: str):
    from storage.database.base import get_db
    from storage.entity.chat import ChatEntity

    with get_db() as session:
        return session.query(ChatEntity.chat_id, ChatEntity.backend, ChatEntity.status).filter(
            ChatEntity.user_id == user_id,
            ChatEntity.chat_id == chat_id,
        ).first()


def read_chat(user_id: int, chat_id: str, offset: int = 0, limit: int = 50,
              now: datetime | None = None) -> dict | None:
    """The chat's stored context analysis, or None when the caller does not own it.

    `state` is `none` (nothing ran, nothing uploaded), `pending` (the chat is
    running or has usage rows but no analysis yet), `analyzed`, `partial`, or
    `unsupported` (not a claude_code chat, or no unit could be analysed).
    Requests are paged in unit order then sequence. Expired detail is not
    returned; its unit totals still are.
    """
    chat = _owned_chat(user_id, chat_id)
    if chat is None:
        return None
    now = now or _now()
    cutoff = int((now - timedelta(days=DETAIL_DAYS)).timestamp())
    body = {
        "chat_id": chat_id,
        "backend": chat.backend or "",
        "chat_running": chat.status == "running",
        "token_method": None,
        "sessions": [],
        "summary": None,
        "requests": {"items": [], "offset": offset, "limit": limit, "total": 0, "next_offset": None},
        "contributors": {"by_size": [], "by_exposure": []},
        "cost": {"state": "unavailable", "reason": "no_validated_per_request_cost"},
        "historical_completeness": "unknown",
    }
    if (chat.backend or "") != "claude_code":
        return {**body, "state": "unsupported", "reason": "backend_not_claude_code"}

    units = repo.units_for_chat(user_id, chat_id)
    if not units:
        pending = body["chat_running"] or repo.chat_has_usage(user_id, chat_id)
        return {**body, "state": "pending" if pending else "none"}

    live = [u.session_id for u in units if u.analyzed_at_unix >= cutoff]
    start = max(offset - 1, 0)
    rows, total = repo.request_page(user_id, chat_id, live, start, limit + (offset - start))
    previous = rows[0] if offset > 0 and rows else None
    page = rows[1:] if offset > 0 else rows
    items = []
    for row in page:
        items.append(_request_view(row, previous))
        previous = row
    methods = sorted({u.token_method for u in units})
    return {
        **body,
        "state": _chat_state(units),
        "token_method": methods[0] if len(methods) == 1 else methods,
        "sessions": [_unit_view(u, cutoff) for u in units],
        "summary": _chat_summary(units),
        "requests": {
            "items": items,
            "offset": offset,
            "limit": limit,
            "total": total,
            "next_offset": offset + limit if offset + limit < total else None,
        },
        "contributors": {
            by: [_contributor_view(c) for c in repo.top_contributors(user_id, chat_id, live, key, TOP_CONTRIBUTORS)]
            for by, key in (("by_size", "size"), ("by_exposure", "exposure"))
        },
    }
