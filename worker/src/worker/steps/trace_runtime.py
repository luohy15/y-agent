"""Runtime-evidence refresh for the watchdog pass (todo 4070, todo 4077).

One probe per owner, written to `trace_runtime_snapshot`, so both the todo list
and the under-lock fault recheck derive from the same evidence. Two writers own
that table: this module's scheduled `refresh_trace_runtime`, and the
session-end reconcile's one owner probe (`worker.session_end`). No API, CLI or
module-host path writes it.
"""

from typing import Dict, Optional, Set

from loguru import logger

from agent.ec2_wake import is_vm_asleep
from agent.vm_command import execute_vm_command
from storage.database.base import get_db
from storage.entity.todo import TodoEntity
from storage.repository.trace_runtime import (trace_runtime_roles,
                                              upsert_snapshot)
from storage.service import vm_config as vm_service
from storage.util import get_unix_timestamp

PROBE_SCRIPT = (
    "tmux list-panes -a -F '#{session_name}:#{pane_dead}:#{pane_pid}:#{pane_current_command}' 2>/dev/null; "
    "echo @@PS@@; ps -e -o pid=,ppid=,comm="
)


def _live_pane(cur, pane_pid, tree) -> bool:
    if cur and cur.rsplit("/", 1)[-1] not in {"sh", "bash", "zsh", "fish", "dash", "sleep"}:
        return True
    pending, seen = [pane_pid], set()
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        for child, command in tree.get(pid, []):
            if command.rsplit("/", 1)[-1] != "sleep":
                return True
            pending.append(child)
    return False


def parse_probe(text: str) -> Optional[Dict[str, list]]:
    """A complete process snapshot distinguishes idle prompts from shell jobs.

    Returns `{todo_id: [session names]}` for live panes, or None when the
    snapshot itself is unknown (missing marker, no parseable ps rows, or a
    tmux section whose lines do not match the four colon-separated fields).
    """
    panes, marker, processes = text.partition("@@PS@@\n")
    if not marker:
        return None
    tree, pids = {}, set()
    for line in processes.splitlines():
        fields = line.split(None, 2)
        if len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit():
            continue
        pid, parent, command = fields
        pids.add(pid)
        tree.setdefault(parent, []).append((pid, command))
    if not pids:
        return None
    live: Dict[str, Set[str]] = {}
    saw_pane_line = False
    parsed_pane = False
    for line in panes.splitlines():
        if not line.strip():
            continue
        saw_pane_line = True
        fields = line.split(":", 3)
        if len(fields) != 4:
            continue
        parsed_pane = True
        name, dead, pane_pid, command = fields
        purpose, separator, todo_id = name.rpartition("-")
        if dead != "0" or not separator or not purpose or not todo_id or name.startswith("cc-"):
            continue
        if _live_pane(command, pane_pid, tree if pane_pid in pids else {}):
            live.setdefault(todo_id, set()).add(name)
    if saw_pane_line and not parsed_pane:
        return None
    return {todo_id: sorted(names) for todo_id, names in live.items()}


async def probe_owner(user_id: int) -> Optional[Dict[str, list]]:
    """Read only this owner's default VM; None is unknown, `{}` is no live job."""
    try:
        vm = vm_service.get_config(user_id, "default")
        if vm is None or is_vm_asleep(vm):
            return {}
        output = await execute_vm_command(
            vm, ["sh", "-c", PROBE_SCRIPT],
            work_dir="", wake=False, timeout=10, check=False,
        )
        return parse_probe(output)
    except Exception:
        logger.exception("trace_runtime: probe unavailable: user_id={}", user_id)
        return None


def _candidate_owners() -> Set[int]:
    """Every owner with an active todo whose trace has no SQL-running chat.

    A running chat is already evidence, so that trace needs no probe.
    """
    with get_db() as session:
        rows = (session.query(TodoEntity.user_id, TodoEntity.todo_id)
                .filter(TodoEntity.status == "active").distinct().all())
        roles = trace_runtime_roles(session, {row[0] for row in rows}, {row[1] for row in rows})
    return {
        user_id for user_id, trace_id in rows
        if (roles.get((user_id, trace_id)) or (0, 0, 0, 0))[1:3] == (0, 0)
    }


async def refresh_trace_runtime(now_ms: Optional[int] = None) -> dict:
    """Probe each candidate owner once and store the result.

    A failed write is logged and counted; it never aborts the other owners.
    """
    now_ms = now_ms if now_ms is not None else get_unix_timestamp()
    owners = _candidate_owners()
    counts = {"owners": len(owners), "written": 0, "unknown": 0, "failed": 0}
    for user_id in sorted(owners):
        jobs = await probe_owner(user_id)
        try:
            upsert_snapshot(user_id, now_ms, ok=jobs is not None, jobs=jobs or {})
            counts["written"] += 1
            if jobs is None:
                counts["unknown"] += 1
        except Exception:
            logger.exception("trace_runtime: snapshot write failed: user_id={}", user_id)
            counts["failed"] += 1
    return {"status": "ok", "action": "trace_runtime", **counts}
