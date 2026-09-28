"""`y usage ingest-transcripts`: upload attributed Claude Code transcript usage.

The transcript JSONL on the VM is the source. Only requests the server can
positively attribute to one of the owner's chats leave the machine, and even
those leave as ids and counters: no message text, no paths. A file that
matches nothing is counted and stays local.

State is per owner and per API base, so two accounts scanning the same VM do
not share a checkpoint. A file is settled only when its upload fully succeeded,
and reopened when its size or mtime changes. An unmatched or partly
unattributed file is retried with backoff until 24h after its mtime; one with
rejected rows or conflicts keeps retrying. Every run record discloses what all
files on disk still owe, including the ones it skipped.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click

from yagent.api_client import api_request, load_auth


PROJECTS_DIR = Path.home() / ".claude" / "projects"
STATE_DIR_NAME = "usage-transcripts"

MAX_ROWS = 500
MAX_BYTES = 512 * 1024
RETRY_BACKOFF = timedelta(hours=1)
SETTLE_AFTER = timedelta(hours=24)
# 1h doubling, capped at 2^5 = 32h: past the 24h cutoff, well inside retention.
MAX_BACKOFF_DOUBLINGS = 5

# The trace id is one token. Either alternative stops before `]`, and the chat
# id is read once, after `to_chat:`. A routine prefix has no trace id. The VM
# corpus only has [0-9a-z] chat ids; the hyphen is accepted because the server
# validates chat ids with the same class. The trace id stops at whitespace or
# the closing bracket so it cannot swallow the rest of the prefix.
PREFIX_RE = re.compile(
    r"^\[(?:trace:([^\s\]]+)|routine:[^\]\n]*)[^\]\n]*?to_chat:([0-9a-z-]+)\]"
)
COUNTERS = ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens")

RUN_FIELDS = (
    "files_seen", "files_uploaded", "files_unmatched", "files_in_progress",
    "files_failed", "malformed_lines", "rows_sent", "rows_rejected",
    "unattributed_requests", "unsupported_subagent_requests",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def api_base() -> str:
    """The API this run talks to. The state file is keyed on it."""
    base = os.getenv("Y_API_BASE")
    if base:
        return base.rstrip("/")
    return load_auth().get("web_url", "https://yovy.app").rstrip("/")


def state_path(base: str, owner_user_id: str) -> Path:
    """Where this owner+API pair keeps its checkpoint. Nothing else shares it."""
    home = Path(os.path.expanduser(os.getenv("Y_AGENT_HOME", "~/.y-agent")))
    digest = hashlib.sha256(f"{base}|{owner_user_id}".encode()).hexdigest()[:16]
    return home / STATE_DIR_NAME / f"{digest}.json"


def _text_of(record: dict) -> str:
    """The first text of a user record, which is where the dispatch prefix is."""
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else record.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                return block["text"]
            if isinstance(block, str):
                return block
    return ""


def _is_meta(record: dict) -> bool:
    return bool(record.get("isMeta"))


def _request_of(record: dict):
    """(request id, message) for a counted assistant record, else None."""
    if record.get("type") != "assistant":
        return None
    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    request_id = message.get("id")
    if not isinstance(request_id, str) or not request_id or message.get("model") == "<synthetic>":
        return None
    return request_id, message


def parse_file(path: Path) -> dict:
    """Parse one transcript into segments of requests.

    Dispatch segments take their chat and trace from the latest preceding
    prefix. Requests before the first prefix are session-level. The last
    record for a request id anywhere in the file wins, including its segment.
    A sidechain request is counted and dropped. A malformed middle line is
    counted and skipped. A final line with no newline or bad JSON is a record
    still being written: the file is in progress, its complete rows may still
    be uploaded, but it is not settled. Blank lines are ignored.
    """
    hints: list[dict | None] = [None]
    latest: dict[str, tuple[int, dict]] = {}
    sidechain_ids: set[str] = set()
    malformed = 0
    in_progress = False

    try:
        lines = path.read_bytes().splitlines(keepends=True)
    except OSError:
        return _empty_parse(malformed=0, in_progress=True, unreadable=True)

    while lines and not lines[-1].strip():
        lines.pop()
    for index, raw in enumerate(lines):
        final = index == len(lines) - 1
        if not raw.strip():
            continue
        if not raw.endswith(b"\n"):
            # A record still being written. Keep what is whole; retry the rest.
            in_progress = True
            break
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            record = None
        if not isinstance(record, dict):
            malformed += 1
            if final:
                # The same damage on the final line is a record still being
                # flushed, so the file is not settled.
                in_progress = True
            continue
        if record.get("isSidechain") is True:
            found = _request_of(record)
            if found:
                sidechain_ids.add(found[0])
            continue
        # A tool result is a user-typed record but never carries a dispatch prefix.
        if record.get("type") == "user" and not _is_meta(record) and not record.get("toolUseResult"):
            match = PREFIX_RE.match(_text_of(record).lstrip())
            if match:
                hints.append({"chat_id": match.group(2), "trace_id": match.group(1)})
                continue
        found = _request_of(record)
        if not found:
            continue
        request_id, message = found
        model = message.get("model")
        usage = message.get("usage") if isinstance(message.get("usage"), dict) else None
        latest.pop(request_id, None)
        latest[request_id] = (len(hints) - 1, {
            "request_id": request_id,
            "model": model if isinstance(model, str) else "",
            "requested_at": record.get("timestamp") or message.get("timestamp") or "",
            "usage": {name: usage.get(name) for name in COUNTERS} if usage else None,
        })

    segments = [{"hint": hint, "requests": {}} for hint in hints]
    for request_id, (position, request) in latest.items():
        segments[position]["requests"][request_id] = request
    segments = [segment for segment in segments if segment["requests"] or segment["hint"] is not None]
    return {
        "segments": segments,
        "malformed_lines": malformed,
        "in_progress": in_progress,
        "unsupported_subagent_requests": len(sidechain_ids),
    }


def _empty_parse(malformed: int, in_progress: bool, unreadable: bool) -> dict:
    return {
        "segments": [],
        "malformed_lines": malformed,
        "in_progress": in_progress,
        "unsupported_subagent_requests": 0,
        "unreadable": unreadable,
    }


def transcript_files(root: Path) -> tuple[list[Path], list[Path]]:
    """Transcript files, and the files under a subagents directory.

    Subagent files are never uploaded. Their requests are counted and skipped.
    """
    files = []
    subagent_files = []
    if not root.exists():
        return files, subagent_files
    for path in sorted(root.rglob("*.jsonl")):
        if "subagents" in path.parts:
            subagent_files.append(path)
            continue
        files.append(path)
    return files, subagent_files


def _subagent_requests(path: Path) -> int:
    """Distinct assistant request ids in a subagent file. Nothing is uploaded."""
    ids = set()
    try:
        lines = path.read_bytes().splitlines()
    except OSError:
        return 0
    for raw in lines:
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(record, dict):
            found = _request_of(record)
            if found:
                ids.add(found[0])
    return len(ids)


def session_id_of(path: Path) -> str:
    return path.stem


# What one file still owes the run record. Every run reports the sum over all
# files still on disk, scanned now or skipped, so a skipped file never turns an
# earlier exception into a clean zero.
OUTSTANDING_FIELDS = (
    "files_unmatched", "files_in_progress", "files_failed", "malformed_lines",
    "rows_rejected", "unattributed_requests", "unsupported_subagent_requests",
)


# What a failed attempt did measure. A resolve failure only knows what the
# local parse found; an upload failure also knows the attribution outcome.
LOCAL_FIELDS = ("malformed_lines", "unsupported_subagent_requests", "files_in_progress")
RESOLVED_FIELDS = LOCAL_FIELDS + ("files_unmatched", "unattributed_requests")


def _no_conflicts() -> dict:
    return {"session": 0, "chat": 0, "model": 0}


def _blank_outstanding() -> dict:
    return {**{field: 0 for field in OUTSTANDING_FIELDS}, "conflicts": _no_conflicts()}


class Scanner:
    """One ingest run. Transport is injected so tests never touch the network."""

    def __init__(self, transport, state_file: Path, now: datetime | None = None, dry_run: bool = False):
        self.transport = transport
        self.state_file = state_file
        self.now = now or _now()
        self.dry_run = dry_run
        self.counts = {field: 0 for field in RUN_FIELDS}
        self.conflicts = _no_conflicts()
        self.attributable_rows = 0
        self.attributable_chats: set[str] = set()
        self.owner_user_id: str | None = None

    def run(self, root: Path, owner_user_id: str | None = None) -> dict:
        """Scan, upload what is attributed, and checkpoint what fully succeeded.

        The owner id comes from a resolve that already succeeded. When the
        caller has not done one, this resolves first, before any state is read
        or written: that id decides which state file is even ours.
        """
        self.owner_user_id = owner_user_id or self.transport.resolve_owner([])
        state = self._load_state()
        files, subagent_files = transcript_files(root)
        for path in subagent_files:
            self.counts["unsupported_subagent_requests"] += _subagent_requests(path)
        for path in files:
            self._scan_file(path, state)
        # A transcript Claude Code has cleaned up owes nothing any more.
        present = {str(path) for path in files}
        state["files"] = {key: value for key, value in state["files"].items() if key in present}
        if not self.dry_run:
            self._save_state(state)
        return self._summary(state)

    def _scan_file(self, path: Path, state: dict) -> None:
        key = str(path)
        prior = state["files"].get(key, {})
        try:
            stat = path.stat()
        except OSError:
            return
        # A settled file is settled at a specific size and mtime. A transcript
        # keeps growing after its first clean scan, so any change reopens it.
        unchanged = prior.get("size") == stat.st_size and prior.get("mtime") == stat.st_mtime
        if unchanged and (prior.get("settled") or not self._due(prior)):
            # Settled, or waiting out its backoff. Either way it still
            # discloses what it owes.
            self._add(prior.get("outstanding") or {})
            return

        self.counts["files_seen"] += 1
        parsed = parse_file(path)
        owed = _blank_outstanding()
        owed["malformed_lines"] = parsed["malformed_lines"]
        owed["unsupported_subagent_requests"] = parsed["unsupported_subagent_requests"]
        owed["files_in_progress"] = int(parsed["in_progress"])

        session_id = session_id_of(path)
        hints = [segment["hint"] for segment in parsed["segments"] if segment["hint"]]
        try:
            attribution = self.transport.resolve(session_id, hints)
        except TransportError:
            # A 5xx or a dropped connection aborts the run. A dry run has
            # uploaded nothing and must not write a checkpoint either.
            self._fail(state, key, prior, stat, owed, remeasured=LOCAL_FIELDS)
            raise
        except ClientError:
            # A 4xx is this file's problem. It is counted and retried next
            # run; the rest of the scan continues.
            self._fail(state, key, prior, stat, owed, remeasured=LOCAL_FIELDS)
            return
        attributed, unattributed = self._attribute(parsed["segments"], attribution)
        had_requests = any(segment["requests"] for segment in parsed["segments"])
        if attributed:
            owed["unattributed_requests"] = unattributed
        elif had_requests:
            # No segment validated: the whole file is unmatched, typically a
            # personal session. It is disclosed as a file, not as requests.
            owed["files_unmatched"] = 1

        if attributed and self.dry_run:
            self.attributable_rows += len(attributed)
            self.attributable_chats.update(row["chat_id"] for row in attributed)
        elif attributed:
            try:
                result = self.transport.upload(session_id, attributed)
            except (TransportError, ClientError) as exc:
                # The batches that did go through measured something; keep
                # the larger of that and what the file already owed.
                partial = getattr(exc, "partial", None) or {}
                self.counts["rows_sent"] += int(partial.get("sent") or 0)
                owed["rows_rejected"] = int(partial.get("rejected") or 0)
                owed["conflicts"] = {
                    field: int((partial.get("conflicts") or {}).get(field) or 0)
                    for field in owed["conflicts"]
                }
                self._fail(state, key, prior, stat, owed, remeasured=RESOLVED_FIELDS, at_least=True)
                if isinstance(exc, TransportError):
                    # A 5xx or a dropped connection aborts the whole run. The
                    # file stays unsettled and no run record is posted.
                    raise
                return
            self.counts["files_uploaded"] += 1
            self.counts["rows_sent"] += result["sent"]
            owed["rows_rejected"] = result["rejected"]
            for field in owed["conflicts"]:
                owed["conflicts"][field] = int(result["conflicts"].get(field, 0))

        self._add(owed)
        state["files"][key] = self._record(prior, stat, owed, self._settles(stat, owed))

    def _settles(self, stat, owed: dict) -> bool:
        """Whether this file is done.

        A clean file settles at once. The 24h cutoff after the file's mtime
        settles only a file that is unmatched or partly unattributed. A file
        still being written, or one with rejected rows or identity conflicts,
        never settles by age: those are losses that must stay disclosed and
        be retried.
        """
        if owed["files_in_progress"] or owed["rows_rejected"] or any(owed["conflicts"].values()):
            return False
        if not owed["files_unmatched"] and not owed["unattributed_requests"]:
            return True
        mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        return self.now - mtime >= SETTLE_AFTER

    def _attribute(self, segments: list[dict], attribution: dict) -> tuple[list[dict], int]:
        """Rows to upload, and how many requests had no validated chat."""
        valid = {
            (hint["chat_id"], hint.get("trace_id"))
            for hint in attribution.get("hints", [])
            if hint.get("valid")
        }
        rows = []
        unattributed = 0
        for segment in segments:
            requests = list(segment["requests"].values())
            hint = segment["hint"]
            if hint is not None and (hint["chat_id"], hint.get("trace_id")) in valid:
                # The hint travels with the row, so the upload can re-check the
                # same chat and trace resolve just validated.
                claim = {"chat_id": hint["chat_id"], "attribution": "hint",
                         "trace_id": hint.get("trace_id")}
            elif hint is None and attribution.get("session_chat_id"):
                claim = {"chat_id": attribution["session_chat_id"], "attribution": "session",
                         "trace_id": None}
            else:
                unattributed += len(requests)
                continue
            for request in requests:
                rows.append({**request, **claim})
        return rows, unattributed

    def _fail(self, state: dict, key: str, prior: dict, stat, owed: dict,
              remeasured: tuple, at_least: bool = False) -> None:
        """Count a per-file failure and remember it, unless this is a dry run.

        A failed attempt could not remeasure everything. Fields in
        `remeasured` take this attempt's value. Every other fact the file
        already owed is kept, because a transcript only grows and an earlier
        rejection or conflict is still in it. With `at_least`, the rejection
        and conflict counts this attempt did measure (from the batches that
        went through) can raise the kept value but never lower it.

        A dry run resolves ids and stops. It uploads nothing and writes no
        checkpoint, including when the resolve itself fails.
        """
        before = prior.get("outstanding") or {}
        for field in OUTSTANDING_FIELDS:
            if field in remeasured:
                continue
            kept = int(before.get(field) or 0)
            owed[field] = max(kept, owed[field]) if at_least else kept
        kept_conflicts = before.get("conflicts") or {}
        for field in owed["conflicts"]:
            kept = int(kept_conflicts.get(field) or 0)
            owed["conflicts"][field] = max(kept, owed["conflicts"][field]) if at_least else kept
        owed["files_failed"] = 1
        self._add(owed)
        if self.dry_run:
            return
        state["files"][key] = self._record(prior, stat, owed, settled=False)
        self._save_state(state)

    def _add(self, owed: dict) -> None:
        for field in OUTSTANDING_FIELDS:
            self.counts[field] += int(owed.get(field) or 0)
        for field in self.conflicts:
            self.conflicts[field] += int((owed.get("conflicts") or {}).get(field) or 0)

    def _due(self, prior: dict) -> bool:
        nxt = prior.get("next_retry_at")
        if not isinstance(nxt, str):
            return True
        try:
            return self.now >= datetime.fromisoformat(nxt)
        except ValueError:
            return True

    def _record(self, prior: dict, stat, owed: dict, settled: bool) -> dict:
        """A checkpoint for one size and mtime. Unsettled files back off, doubling.

        `failures` counts consecutive unsettled attempts on this exact file
        version. It restarts when the file changes or settles, so a long run
        of clean scans never inflates the first retry after a failure: that
        one waits RETRY_BACKOFF.
        """
        same_version = prior.get("size") == stat.st_size and prior.get("mtime") == stat.st_mtime
        streak = int(prior.get("failures") or 0) if same_version and not prior.get("settled") else 0
        record = {
            "failures": 0 if settled else streak + 1,
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "outstanding": owed,
            "settled": settled,
        }
        if not settled:
            delay = RETRY_BACKOFF * (2 ** min(record["failures"] - 1, MAX_BACKOFF_DOUBLINGS))
            record["next_retry_at"] = _iso(self.now + delay)
        return record

    def _load_state(self) -> dict:
        if not self.state_file.exists():
            return {"files": {}}
        try:
            loaded = json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            return {"files": {}}
        if not isinstance(loaded, dict) or not isinstance(loaded.get("files"), dict):
            return {"files": {}}
        return loaded

    def _save_state(self, state: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state, indent=2).encode()
        fd, tmp = tempfile.mkstemp(dir=self.state_file.parent, suffix=".tmp")
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        try:
            os.replace(tmp, self.state_file)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _summary(self, state: dict) -> dict:
        summary = {
            "owner_user_id": self.owner_user_id,
            "dry_run": self.dry_run,
            **self.counts,
            "conflicts": self.conflicts,
            "state_file": str(self.state_file),
        }
        if not self.dry_run:
            summary["files_settled"] = sum(1 for f in state["files"].values() if f.get("settled"))
        else:
            summary["rows_attributable"] = self.attributable_rows
            summary["chats_attributable"] = len(self.attributable_chats)
        return summary


class TransportError(Exception):
    """5xx or a connection failure. The run aborts and posts no record."""


class ClientError(Exception):
    """4xx for one file. That file is marked failed and retried next run."""


class ApiTransport:
    """The real transport: resolve, upload, and the run record, over the API."""

    def resolve_owner(self, sessions: list[dict]) -> str:
        body = self._post("/api/usage/requests/resolve", {"sessions": sessions})
        user_id = body.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            raise TransportError("resolve returned no owner user_id")
        return user_id

    def resolve(self, session_id: str, hints: list[dict]) -> dict:
        body = self._post("/api/usage/requests/resolve", {"sessions": [{
            "session_id": session_id,
            "hints": [{"chat_id": h["chat_id"], "trace_id": h.get("trace_id")} for h in hints],
        }]})
        sessions = body.get("sessions") or []
        return sessions[0] if sessions else {"session_chat_id": None, "hints": []}

    def upload(self, session_id: str, rows: list[dict]) -> dict:
        sent = 0
        rejected = 0
        conflicts = {"session": 0, "chat": 0, "model": 0}
        for batch in _batches(session_id, rows):
            try:
                body = self._post("/api/usage/requests", {"rows": batch})
            except (TransportError, ClientError) as exc:
                # Earlier batches were stored; report what they measured.
                exc.partial = {"sent": sent, "rejected": rejected, "conflicts": conflicts}
                raise
            sent += len(batch)
            rejected += len(body.get("rejected") or [])
            got = body.get("conflicts") or {}
            for field in conflicts:
                conflicts[field] += int(got.get(field) or 0)
        return {"sent": sent, "rejected": rejected, "conflicts": conflicts}

    def record_run(self, summary: dict, started: datetime, finished: datetime) -> None:
        self._post("/api/usage/requests/ingest-run", {
            "host": socket.gethostname(),
            "started_at": _iso(started),
            "finished_at": _iso(finished),
            **{field: summary.get(field, 0) for field in RUN_FIELDS},
            "conflicts": summary.get("conflicts") or {},
        })

    def _post(self, path: str, payload: dict) -> dict:
        import httpx

        try:
            resp = api_request("POST", path, timeout=60, json=payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                raise TransportError(str(exc)) from exc
            raise ClientError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise TransportError(str(exc)) from exc
        return resp.json()


def _batches(session_id: str, rows: list[dict]) -> list[list[dict]]:
    """Split rows so each request stays within the row count and byte cap."""
    batches: list[list[dict]] = []
    current: list[dict] = []
    for row in rows:
        payload = {"request_id": row["request_id"], "session_id": session_id,
                   "chat_id": row["chat_id"], "model": row["model"],
                   "requested_at": row["requested_at"], "usage": _usage(row["usage"]),
                   "attribution": row.get("attribution"), "trace_id": row.get("trace_id")}
        if current and (len(current) >= MAX_ROWS or _size(current + [payload]) > MAX_BYTES):
            batches.append(current)
            current = []
        current.append(payload)
    if current:
        batches.append(current)
    return batches


def _usage(counters) -> dict | None:
    if counters is None:
        return None
    return {name: value for name, value in counters.items() if value is not None}


def _size(rows: list[dict]) -> int:
    return len(json.dumps({"rows": rows}).encode())


def ingest(root: Path | None = None, dry_run: bool = False, transport=None) -> dict:
    """Run one ingest. Returns the summary; a transport failure exits nonzero."""
    transport = transport or ApiTransport()
    started = _now()
    try:
        owner = transport.resolve_owner([])
    except (TransportError, ClientError) as exc:
        raise click.ClickException(f"could not resolve owner, nothing scanned: {exc}") from exc
    scanner = Scanner(
        transport,
        state_path(api_base(), owner),
        now=started,
        dry_run=dry_run,
    )
    try:
        summary = scanner.run(root or PROJECTS_DIR, owner_user_id=owner)
    except TransportError as exc:
        raise click.ClickException(f"ingest aborted, no run recorded: {exc}") from exc
    if not dry_run:
        try:
            transport.record_run(summary, started, _now())
        except (TransportError, ClientError) as exc:
            raise click.ClickException(f"uploaded, but the run record failed: {exc}") from exc
    return summary


@click.command("ingest-transcripts")
@click.option("--dry-run", is_flag=True, help="Resolve ids, but upload nothing and write no state")
@click.option("--json", "as_json", is_flag=True, help="Print the run summary as JSON")
def ingest_transcripts(dry_run, as_json):
    """Upload attributed Claude Code transcript usage for this owner."""
    summary = ingest(dry_run=dry_run)
    if as_json:
        click.echo(json.dumps(summary, default=str))
        return
    click.echo(
        f"files seen={summary['files_seen']} uploaded={summary['files_uploaded']} "
        f"unmatched={summary['files_unmatched']} in_progress={summary['files_in_progress']} "
        f"failed={summary['files_failed']}"
    )
    click.echo(
        f"rows sent={summary['rows_sent']} rejected={summary['rows_rejected']} "
        f"unattributed={summary['unattributed_requests']} "
        f"subagent={summary['unsupported_subagent_requests']}"
    )
    if dry_run:
        click.echo(
            f"dry run: rows attributable={summary['rows_attributable']} "
            f"chats={summary['chats_attributable']}, nothing uploaded or saved"
        )
