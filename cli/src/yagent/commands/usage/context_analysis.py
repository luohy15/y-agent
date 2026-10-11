"""Local context analysis of one Claude Code transcript (todo 3844).

Explains, per request, what filled the prompt: system prompt, rules / memory,
skills and references, tool schemas, file and other tool results, and
conversation history, next to the observed usage counters. Runs on the VM
beside the 3729 ingest. The result carries sizes, digests, relative labels and
counters only, never a prompt, output, tool input or tool result body.

What a request saw is reconstructed from the parentUuid chain ending just
before its first assistant record, so later output, abandoned branches and
anything before a compaction boundary are excluded. Parallel tool results hang
off their own tool_use record, not the chain, so they are joined by tool_use
id. Whatever the transcript cannot attribute stays unknown: a request with no
prompt snapshot has an unknown system prompt, the first snapshot of a session
carries no tools, and opaque reasoning, images and hidden formatting are never
sized. Category sizes are UTF-8 bytes; token sizes are an estimate from the
named TOKEN_METHOD, distinct from the provider counters.

The compaction boundary shape (system / compact_boundary with parentUuid null,
compactMetadata and logicalParentUuid, then an isCompactSummary user record) is
taken from the Claude Code 2.1.284 CLI, which writes it; no local transcript
contained one when this was written.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from yagent.commands.usage.transcripts import COUNTERS, _request_of

ANALYZER_VERSION = 1
TOKEN_METHOD = "utf8_bytes_div_4_v1"

CATEGORIES = (
    "system_prompt", "rules_memory", "skills_references", "tool_schemas",
    "file_results", "tool_results", "conversation",
)
LARGE_RESULT_BYTES = 40_000
HEAVY_STARTUP_SHARE = 0.3
STARTUP_CATEGORIES = ("rules_memory", "skills_references", "tool_schemas")
RULES_FILES = {"CLAUDE.md", "AGENTS.md", "CLAUDE.local.md"}
HOME_RE = re.compile(r"^/(?:Users|home)/[^/]+/")
# Attachments that are metadata, not prompt content.
METADATA_ATTACHMENTS = {"prompt_snapshot", "deferred_tools_record"}


def analysis_stale(file_record: dict) -> bool:
    """Whether a checkpointed file was analyzed by another analyzer version.

    A settled file is reopened for context analysis only on an explicit
    backfill; this says whether that backfill has work to do.
    """
    return file_record.get("analyzer_version") != ANALYZER_VERSION


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _bytes(text: str) -> int:
    return len(text.encode("utf-8"))


def _tokens(size: int | None) -> int | None:
    return None if size is None else (size + 3) // 4


def safe_label(path, cwd) -> str | None:
    """A relative label for a path: under cwd, else under home, else the name."""
    if not isinstance(path, str) or not path:
        return None
    if isinstance(cwd, str) and cwd and path.startswith(cwd.rstrip("/") + "/"):
        return path[len(cwd.rstrip("/")) + 1:]
    home = HOME_RE.match(path)
    if home:
        return path[home.end():]
    return Path(path).name if path.startswith("/") else path


def _rendered(record: dict, overhead: dict) -> str | None:
    """What an attachment put on the wire. A part is a string or a block list."""
    rendered = record.get("rendered")
    if not isinstance(rendered, list):
        return None
    text = []
    for part in rendered:
        if isinstance(part, dict):
            body, images = _result_text(part.get("content"))
            text.append(body)
            overhead["images"] += images
    return "".join(text)


def _result_text(content) -> tuple[str, int]:
    """Text of a tool_result, and how many image parts it had."""
    if isinstance(content, str):
        return content, 0
    text, images = [], 0
    for part in content if isinstance(content, list) else []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            text.append(part["text"])
        elif part.get("type") == "image":
            images += 1
    return "".join(text), images


def _read_records(path: Path):
    """(records with file index, file gaps), or None when unreadable.

    The same line rules as the 3729 ingest: a malformed middle line is counted
    and skipped, a final line without a newline or with bad JSON is a record
    still being written.
    """
    try:
        lines = path.read_bytes().splitlines(keepends=True)
    except OSError:
        return None
    while lines and not lines[-1].strip():
        lines.pop()
    records = []
    gaps = {"malformed_lines": 0, "in_progress": False, "sidechain_records": 0, "duplicate_records": 0}
    for index, raw in enumerate(lines):
        if not raw.strip():
            continue
        if not raw.endswith(b"\n"):
            gaps["in_progress"] = True
            break
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            record = None
        if not isinstance(record, dict):
            gaps["malformed_lines"] += 1
            if index == len(lines) - 1:
                gaps["in_progress"] = True
            continue
        records.append(record)
    return records, gaps


class _Span:
    __slots__ = ("occurrence_id", "category", "origin", "label", "digest", "size")

    def __init__(self, occurrence_id, category, origin, label, text=None, size=None, digest=None):
        self.occurrence_id = occurrence_id
        self.category = category
        self.origin = origin
        self.label = label
        self.size = _bytes(text) if size is None else size
        self.digest = digest or (_digest(text) if text is not None else None)


class _Transcript:
    def __init__(self, records: list[dict], gaps: dict):
        self.gaps = gaps
        self.by_uuid: dict[str, tuple[int, dict]] = {}
        self.order: list[str] = []
        self.first_record: dict[str, int] = {}
        self.final_message: dict[str, tuple[int, dict, dict]] = {}
        self.tool_uses: dict[str, dict] = {}
        self.results_by_use: dict[str, list[int]] = {}
        self.boundaries: list[int] = []
        self.versions: set[str] = set()
        self.records = records
        for index, record in enumerate(records):
            if record.get("isSidechain") is True:
                gaps["sidechain_records"] += 1
                continue
            if isinstance(record.get("version"), str):
                self.versions.add(record["version"])
            uuid = record.get("uuid")
            if isinstance(uuid, str):
                if uuid in self.by_uuid:
                    gaps["duplicate_records"] += 1
                    continue
                self.by_uuid[uuid] = (index, record)
            if _is_boundary(record):
                self.boundaries.append(index)
            found = _request_of(record)
            if found:
                request_id, message = found
                if request_id not in self.first_record:
                    self.first_record[request_id] = index
                    self.order.append(request_id)
                self.final_message[request_id] = (index, record, message)
                for block in _blocks(message):
                    if block.get("type") == "tool_use" and isinstance(block.get("id"), str):
                        self.tool_uses.setdefault(block["id"], block)
            if record.get("type") == "user":
                message = record.get("message")
                for block in _blocks(message if isinstance(message, dict) else {}):
                    if block.get("type") == "tool_result" and isinstance(block.get("tool_use_id"), str):
                        self.results_by_use.setdefault(block["tool_use_id"], []).append(index)
                if record.get("isMeta") and isinstance(record.get("sourceToolUseID"), str):
                    self.results_by_use.setdefault(record["sourceToolUseID"], []).append(index)

    def context(self, request_id: str):
        """Records (by file index) a request saw, its boundary, and chain gaps."""
        first_index = self.first_record[request_id]
        parent = self.records[first_index].get("parentUuid")
        chain: list[int] = []
        boundary = None
        broken = False
        seen = set()
        while isinstance(parent, str) and parent not in seen:
            seen.add(parent)
            found = self.by_uuid.get(parent)
            if not found:
                broken = True
                break
            index, record = found
            if _is_boundary(record):
                boundary = index
                break
            chain.append(index)
            parent = record.get("parentUuid")
        included = set(chain)
        # Parallel tool results and loaded skill bodies sit off the chain,
        # parented to their own tool_use record.
        for index in chain:
            message = self.records[index].get("message")
            if self.records[index].get("type") != "assistant" or not isinstance(message, dict):
                continue
            for block in _blocks(message):
                if block.get("type") == "tool_use":
                    for result in self.results_by_use.get(block.get("id"), []):
                        if result < first_index and (boundary is None or result > boundary):
                            included.add(result)
        return sorted(included), boundary, broken


def _is_boundary(record: dict) -> bool:
    return record.get("type") == "system" and record.get("subtype") == "compact_boundary"


def _blocks(message: dict) -> list[dict]:
    content = message.get("content")
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def _classify_result(tool_use: dict | None, cwd) -> tuple[str, str, str | None]:
    """(category, origin, label) of a tool result, by the call that made it."""
    if not tool_use:
        return "tool_results", "tool_result", None
    name = tool_use.get("name")
    args = tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {}
    if name == "Skill":
        return "skills_references", "skill_result", args.get("skill") if isinstance(args.get("skill"), str) else None
    if name == "Read":
        path = args.get("file_path")
        label = safe_label(path, cwd)
        if isinstance(path, str) and Path(path).name in RULES_FILES:
            return "rules_memory", "rules_read", label
        if isinstance(path, str) and ("/.agents/references/" in path or "/skills/" in path):
            return "skills_references", "reference_read", label
        return "file_results", "file_read", label
    return "tool_results", "tool_result", name if isinstance(name, str) else None


def _record_spans(transcript: _Transcript, index: int, overhead: dict, used_blocks: set) -> list[_Span]:
    """Content spans one in-context record contributes."""
    record = transcript.records[index]
    uuid = record.get("uuid") or f"line{index}"
    cwd = record.get("cwd")
    kind = record.get("type")
    spans: list[_Span] = []
    if kind == "attachment":
        attachment = record.get("attachment") if isinstance(record.get("attachment"), dict) else {}
        atype = attachment.get("type")
        rendered = _rendered(record, overhead)
        if atype in METADATA_ATTACHMENTS:
            return spans
        if atype == "instructions":
            files = [f for f in attachment.get("files") or [] if isinstance(f, dict) and isinstance(f.get("content"), str)]
            listed = 0
            for position, item in enumerate(files):
                spans.append(_Span(f"{uuid}:{position}", "rules_memory", "instructions",
                                   safe_label(item.get("path"), cwd), item["content"]))
                listed += _bytes(item["content"])
            if rendered is not None and _bytes(rendered) > listed:
                spans.append(_Span(f"{uuid}:rendering", "rules_memory", "instructions_rendering", None,
                                   size=_bytes(rendered) - listed, digest=_digest(rendered)))
            return spans
        if rendered is None:
            return spans
        if atype == "nested_memory":
            spans.append(_Span(uuid, "rules_memory", "nested_memory", safe_label(attachment.get("path"), cwd), rendered))
        elif atype == "skill_listing":
            spans.append(_Span(uuid, "skills_references", "skill_listing", None, rendered))
        elif atype == "deferred_tools_delta":
            spans.append(_Span(uuid, "tool_schemas", "deferred_tools_delta", None, rendered))
        else:
            spans.append(_Span(uuid, "conversation", f"attachment:{atype}", None, rendered))
        return spans
    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    if kind == "user":
        if record.get("isCompactSummary"):
            text = message.get("content")
            text = text if isinstance(text, str) else "".join(
                b.get("text") or "" for b in _blocks(message) if b.get("type") == "text")
            return [_Span(uuid, "conversation", "compact_summary", None, text)]
        source = record.get("sourceToolUseID")
        skill_use = transcript.tool_uses.get(source) if isinstance(source, str) else None
        content = message.get("content")
        if isinstance(content, str):
            return [_Span(uuid, "conversation", "user_text", None, content)]
        for position, block in enumerate(_blocks(message)):
            btype = block.get("type")
            if btype == "tool_result":
                tool_id = block.get("tool_use_id")
                key = ("result", tool_id)
                if key in used_blocks:
                    continue
                used_blocks.add(key)
                text, images = _result_text(block.get("content"))
                overhead["images"] += images
                category, origin, label = _classify_result(transcript.tool_uses.get(tool_id), cwd)
                spans.append(_Span(f"{uuid}:{tool_id}", category, origin, label, text))
            elif btype == "text" and isinstance(block.get("text"), str):
                if record.get("isMeta") and skill_use and skill_use.get("name") == "Skill":
                    skill = (skill_use.get("input") or {}).get("skill")
                    spans.append(_Span(f"{uuid}:{position}", "skills_references", "skill_body",
                                       skill if isinstance(skill, str) else None, block["text"]))
                else:
                    spans.append(_Span(f"{uuid}:{position}", "conversation",
                                       "meta_text" if record.get("isMeta") else "user_text", None, block["text"]))
            elif btype == "image":
                overhead["images"] += 1
        return spans
    if kind == "assistant":
        for position, block in enumerate(_blocks(message)):
            btype = block.get("type")
            if btype == "text" and isinstance(block.get("text"), str):
                spans.append(_Span(f"{uuid}:{position}", "conversation", "assistant_text", None, block["text"]))
            elif btype == "thinking" and isinstance(block.get("thinking"), str):
                spans.append(_Span(f"{uuid}:{position}", "conversation", "thinking", None, block["thinking"]))
            elif btype == "redacted_thinking":
                overhead["opaque_reasoning_blocks"] += 1
            elif btype == "tool_use":
                key = ("use", block.get("id"))
                if key in used_blocks:
                    continue
                used_blocks.add(key)
                name = block.get("name")
                spans.append(_Span(f"{uuid}:{block.get('id')}", "conversation", "tool_input",
                                   name if isinstance(name, str) else None,
                                   json.dumps(block.get("input"), sort_keys=True)))
    return spans


def _snapshot_spans(transcript: _Transcript, included: list[int]) -> tuple[list[_Span] | None, list[_Span] | None]:
    """System prompt and tool schema spans from the latest snapshots seen.

    None means no snapshot (or no snapshot with tools) was in context, which is
    unknown, not empty. The first snapshot of a session carries no tools.
    """
    system = tools = None
    for index in reversed(included):
        record = transcript.records[index]
        attachment = record.get("attachment") if record.get("type") == "attachment" else None
        if not isinstance(attachment, dict) or attachment.get("type") != "prompt_snapshot":
            continue
        if system is None and "systemPrompt" in attachment:
            prompt = attachment["systemPrompt"]
            text = "".join(p for p in prompt if isinstance(p, str)) if isinstance(prompt, list) else str(prompt or "")
            system = [_Span(f"system:{_digest(text)}", "system_prompt", "system_prompt", None, text)]
        if tools is None and isinstance(attachment.get("tools"), list):
            tools = []
            for tool in attachment["tools"]:
                if not isinstance(tool, dict):
                    continue
                name = tool.get("name") if isinstance(tool.get("name"), str) else ""
                body = name + str(tool.get("description") or "") + json.dumps(tool.get("schema"), sort_keys=True)
                tools.append(_Span(f"tool:{name}:{_digest(body)}", "tool_schemas", "tool_schema", name or None, body))
        if system is not None and tools is not None:
            break
    return system, tools


def _usage(message: dict) -> dict:
    usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
    out = {}
    for name, key in COUNTERS.items():
        value = usage.get(key)
        out[name] = value if isinstance(value, int) and not isinstance(value, bool) else None
    return out


def analyze_file(path: Path) -> dict:
    """Analyze one transcript file. Never raises on content; gaps are disclosed."""
    read = _read_records(path)
    base = {
        "analyzer_version": ANALYZER_VERSION,
        "token_method": TOKEN_METHOD,
        "session_id": path.stem,
    }
    if read is None:
        return {**base, "state": "unsupported", "cli_versions": [], "gaps": {"unreadable": True},
                "events": [], "requests": [], "contributors": [], "summary": _summary([]), "suggestions": []}
    transcript = _Transcript(*read)

    events = []
    requests = []
    occurrences: dict[str, dict] = {}
    previous_epoch = None
    previous_prompt = None
    for sequence, request_id in enumerate(transcript.order, start=1):
        included, boundary, broken = transcript.context(request_id)
        epoch = transcript.boundaries.index(boundary) + 1 if boundary is not None else 0
        gaps = []
        if broken:
            gaps.append("broken_chain")
        if boundary is not None:
            meta = transcript.records[boundary].get("compactMetadata") or {}
            preserved = bool(meta.get("preservedSegment") or meta.get("preservedMessages"))
            if preserved:
                gaps.append("compaction_preserved_segment")
            if epoch != previous_epoch and not any(e["epoch"] == epoch for e in events):
                events.append({"kind": "compaction", "epoch": epoch, "trigger": meta.get("trigger"),
                               "pre_tokens": meta.get("preTokens"), "post_tokens": meta.get("postTokens"),
                               "before_request": sequence, "preserved_segment": preserved})

        overhead = {"opaque_reasoning_blocks": 0, "images": 0}
        used_blocks: set = set()
        spans: list[_Span] = []
        for index in included:
            spans.extend(_record_spans(transcript, index, overhead, used_blocks))
        system, tools = _snapshot_spans(transcript, included)
        if system is None:
            gaps.append("no_prompt_snapshot")
        else:
            spans.extend(system)
        if tools is None:
            gaps.append("no_tool_snapshot")
        else:
            spans.extend(tools)

        sizes = {name: 0 for name in CATEGORIES}
        for span in spans:
            sizes[span.category] += span.size
            entry = occurrences.get(span.occurrence_id)
            if entry is None:
                occurrences[span.occurrence_id] = {
                    "occurrence_id": span.occurrence_id, "category": span.category, "origin": span.origin,
                    "label": span.label, "digest": span.digest, "bytes": span.size,
                    "introduced_request": sequence, "exposure_requests": 1,
                }
            else:
                entry["exposure_requests"] += 1
        unknown = {"system_prompt": system is None, "tool_schemas": tools is None and sizes["tool_schemas"] == 0}
        categories = {}
        for name in CATEGORIES:
            size = None if unknown.get(name) else sizes[name]
            categories[name] = {"bytes": size, "estimated_tokens": _tokens(size),
                                "complete": not (name == "tool_schemas" and tools is None) and size is not None}

        _, record, message = transcript.final_message[request_id]
        counters = _usage(message)
        parts = (counters["input_tokens"], counters["cache_creation_tokens"], counters["cache_read_tokens"])
        prompt = sum(parts) if all(p is not None for p in parts) else None
        known_tokens = sum(c["estimated_tokens"] or 0 for c in categories.values())
        residual = prompt - known_tokens if prompt is not None else None
        same_epoch = previous_epoch == epoch
        requests.append({
            "request_id": request_id,
            "sequence": sequence,
            "epoch": epoch,
            "model": message.get("model") if isinstance(message.get("model"), str) else "",
            "requested_at": record.get("timestamp") or "",
            "usage": counters,
            "prompt_tokens": prompt,
            "growth": prompt - previous_prompt if prompt is not None and previous_prompt is not None and same_epoch else None,
            "cache_reuse": counters["cache_read_tokens"] / prompt if prompt else None,
            "categories": categories,
            "unknown_tokens_estimate": residual if residual is not None and residual >= 0 else None,
            "estimate_exceeds_observed": residual is not None and residual < 0,
            "unknown_overhead": {**overhead, "hidden_formatting": True},
            "gaps": gaps,
            "state": "partial" if gaps else "analyzed",
        })
        previous_epoch = epoch
        previous_prompt = prompt

    contributors = sorted(occurrences.values(), key=lambda c: (c["introduced_request"], c["occurrence_id"]))
    file_gaps = transcript.gaps
    damaged = file_gaps["malformed_lines"] or file_gaps["in_progress"] or file_gaps["sidechain_records"]
    return {
        **base,
        "state": "partial" if damaged or any(r["state"] == "partial" for r in requests) else "analyzed",
        "cli_versions": sorted(transcript.versions),
        "gaps": file_gaps,
        "events": events,
        "requests": requests,
        "contributors": contributors,
        "summary": _summary(requests),
        "suggestions": _suggestions(requests, contributors),
    }


def _summary(requests: list[dict]) -> dict:
    """Occupancy (startup / peak / latest) apart from cumulative billed input."""
    known = [r for r in requests if r["prompt_tokens"] is not None]
    prompts = [r["prompt_tokens"] for r in known]
    total = sum(prompts)
    return {
        "requests": len(requests),
        "requests_with_prompt": len(known),
        "startup_prompt_tokens": prompts[0] if prompts else None,
        "peak_prompt_tokens": max(prompts) if prompts else None,
        "latest_prompt_tokens": prompts[-1] if prompts else None,
        "cumulative_input_tokens": total if prompts else None,
        "cache_reuse": sum(r["usage"]["cache_read_tokens"] for r in known) / total if total else None,
        "cost": {"state": "unavailable", "reason": "no_validated_per_request_cost"},
    }


def _suggestions(requests: list[dict], contributors: list[dict]) -> list[dict]:
    """Deterministic hints, worded as correlations, never as promised savings."""
    out = []
    reads: dict[str, list[dict]] = {}
    for c in contributors:
        if c["origin"] in ("file_read", "reference_read", "rules_read") and c["digest"]:
            reads.setdefault(c["digest"], []).append(c)
    for group in reads.values():
        if len(group) > 1:
            out.append({"kind": "repeated_identical_read", "label": group[0]["label"],
                        "occurrences": len(group), "bytes": group[0]["bytes"],
                        "message": f"The same content was read {len(group)} times; every copy stays in context."})
    for c in contributors:
        if c["category"] in ("file_results", "tool_results") and c["bytes"] > LARGE_RESULT_BYTES:
            out.append({"kind": "large_tool_result", "label": c["label"], "bytes": c["bytes"],
                        "introduced_request": c["introduced_request"],
                        "message": f"A {c['bytes']} byte tool result rode along for {c['exposure_requests']} requests."})
    first = next((r for r in requests if r["prompt_tokens"]), None)
    if first:
        startup = sum(first["categories"][name]["estimated_tokens"] or 0 for name in STARTUP_CATEGORIES)
        if startup / first["prompt_tokens"] >= HEAVY_STARTUP_SHARE:
            out.append({"kind": "heavy_startup", "estimated_tokens": startup,
                        "message": "Rules, skill listing and tool schemas are an estimated "
                                   f"{round(100 * startup / first['prompt_tokens'])}% of the first prompt."})
    drops = []
    previous = None
    for r in requests:
        read = r["usage"]["cache_read_tokens"]
        if previous is not None and read is not None and previous["usage"]["cache_read_tokens"] is not None \
                and previous["epoch"] == r["epoch"] and read < previous["usage"]["cache_read_tokens"]:
            drops.append(r["sequence"])
        previous = r
    if drops:
        out.append({"kind": "prefix_change", "requests": drops,
                    "message": "Cache reads fell on these requests, which correlates with a changed "
                               "prompt prefix; it does not prove the cause."})
    return out


MAX_UPLOAD_REQUESTS = 600
MAX_UPLOAD_CONTRIBUTORS = 200
# Fields the analysis computes from counters; the server recomputes them.
_DERIVED = ("prompt_tokens", "growth", "cache_reuse", "unknown_tokens_estimate", "estimate_exceeds_observed")


def _top_contributors(contributors: list[dict]) -> list[dict]:
    """The largest by size and by size x exposure, half the bound each."""
    half = MAX_UPLOAD_CONTRIBUTORS // 2
    by_size = sorted(contributors, key=lambda c: -c["bytes"])[:half]
    by_exposure = sorted(contributors, key=lambda c: -c["bytes"] * c["exposure_requests"])[:half]
    kept = {c["occurrence_id"]: c for c in by_size + by_exposure}
    return sorted(kept.values(), key=lambda c: (c["introduced_request"], c["occurrence_id"]))


def upload_units(analysis: dict, rows: list[dict]) -> list[dict]:
    """One upload per chat the 3729 attribution assigned requests of this file to.

    `rows` are the attributed usage rows (request_id, chat_id, attribution,
    trace_id). A chat gets only its own requests, the contributors those
    requests introduced, and suggestions recomputed over that subset. Suggestion
    text and the analyzer's derived values are not sent; occurrence ids are
    hashed. The latest MAX_UPLOAD_REQUESTS requests are kept and the rest
    counted as omitted.
    """
    claims: dict[str, dict] = {}
    chat_requests: dict[str, set] = {}
    for row in rows:
        chat_id = row["chat_id"]
        chat_requests.setdefault(chat_id, set()).add(row["request_id"])
        # A hint claim is preferred; a session claim is just as valid on its own.
        if chat_id not in claims or (row["attribution"] == "hint" and claims[chat_id]["attribution"] != "hint"):
            claims[chat_id] = {"attribution": row["attribution"], "trace_id": row.get("trace_id")}

    damaged = any(analysis["gaps"].get(name) for name in ("malformed_lines", "in_progress", "sidechain_records"))
    units = []
    for chat_id, ids in chat_requests.items():
        requests = [r for r in analysis["requests"] if r["request_id"] in ids]
        if not requests and analysis["state"] != "unsupported":
            continue
        omitted = max(0, len(requests) - MAX_UPLOAD_REQUESTS)
        requests = requests[omitted:]
        sequences = {r["sequence"] for r in requests}
        contributors = [c for c in analysis["contributors"] if c["introduced_request"] in sequences]
        kept = _top_contributors(contributors)
        suggestions = [{k: v for k, v in s.items() if k != "message"} for s in _suggestions(requests, contributors)]
        if analysis["state"] == "unsupported":
            state = "unsupported"
        elif damaged or omitted or any(r["state"] == "partial" for r in requests):
            state = "partial"
        else:
            state = "analyzed"
        units.append({
            "session_id": analysis["session_id"],
            "chat_id": chat_id,
            **claims[chat_id],
            "analyzer_version": analysis["analyzer_version"],
            "token_method": analysis["token_method"],
            "state": state,
            "cli_versions": analysis["cli_versions"],
            "gaps": analysis["gaps"],
            "events": [e for e in analysis["events"] if e["before_request"] in sequences],
            "requests": [{k: v for k, v in r.items() if k not in _DERIVED} for r in requests],
            "contributors": [{**c, "occurrence_id": _digest(c["occurrence_id"])} for c in kept],
            "suggestions": suggestions[:50],
            "requests_omitted": omitted,
            "contributors_omitted": len(contributors) - len(kept),
        })
    return units
