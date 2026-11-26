"""Bound and check the harness-owned attempt data under a node's run dir.

The launch path ships this file's source to the node and runs it with
`python3 -c` (see `detach._gc_attempts_cmd`), so it must stay stdlib-only, free
of `agent` imports, and Python 3.9 compatible.

Three duties:

* `gc` deletes old attempt groups that no tmux session can still be using,
  oldest first, until the harness-owned total is back under its budget. A live
  `cc-<chat_id>` session (either tmux socket) and any group younger than
  `--min-age` are never touched, and a group is deleted as a whole. A chat's
  staged MCP directories travel with its group; an MCP directory that maps to
  no chat group is only removed after a day. Each chat's check and removal run
  under that chat's `.cc-<chat_id>.lock`, which launch staging holds while it
  creates or replaces a generation, so no replacement can arrive between the
  device/inode check and the unlink; a busy lock keeps the group for a later
  pass. Only bytes actually removed count toward the budget. A socket that
  tmux confirms has no server is empty; any other tmux failure makes the live
  set unknown and deletes nothing.
* `clean` removes one chat's images, codex home and MCP staging that predates
  a given instant, which the monitor sets when its turn ended. Staging created
  by a later turn is newer and is kept, and the same per-chat lock keeps a
  concurrent launch's staging out of the check-to-delete window. A staged
  Codex home is deleted only after its rollouts have been copied back to
  `$HOME/.codex/sessions`; a failed copy keeps the home. Every removal (clean,
  GC, and the reaper's own routine) follows that rule.
* `free` reports the run dir's available bytes against a launch floor. The
  launch refuses to start a turn below that floor: without room for its own
  logs the turn can only die mid-way (2026-11-26 /tmp exhaustion, todo 4487).
"""

import fcntl
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import time


DEFAULT_BUDGET_BYTES = 1024 ** 3
DISK_FLOOR_BYTES = 500 * 1024 * 1024
# codex app-server stages a ~96 MB CODEX_HOME before it starts.
CODEX_APP_SERVER_DISK_FLOOR_BYTES = 700 * 1024 * 1024
MIN_GROUP_AGE_SECONDS = 60 * 60
UNMAPPED_MCP_MIN_AGE_SECONDS = 24 * 60 * 60
MCP_PREFIX = "y-mcp-"
ATTEMPT_SUFFIXES = (
    ".stdin", ".stdout", ".stderr", ".exit", ".model-catalog.json",
    ".killed", ".claude-ec", ".codex-home", "-images",
)


def chat_id_for(name):
    """The chat id a harness-owned `cc-*` entry belongs to, or None."""
    if not name.startswith("cc-"):
        return None
    for suffix in ATTEMPT_SUFFIXES:
        if name.endswith(suffix) and len(name) > len("cc-") + len(suffix):
            return name[len("cc-"):-len(suffix)]
    return None


def mcp_hash(chat_id):
    """The hash prefix `mcp.staging.chat_prefix` derives from a chat id."""
    return hashlib.sha256(chat_id.encode()).hexdigest()[:24]


def mcp_hash_for_name(name):
    if not name.startswith(MCP_PREFIX):
        return None
    prefix = name[len(MCP_PREFIX):].split("-", 1)[0]
    return prefix if len(prefix) == 24 else None


def entry_bytes_and_mtime(path):
    """(bytes, newest mtime) of one entry without following symlinks."""
    try:
        info = os.lstat(path)
    except OSError:
        return 0, 0.0
    if stat.S_ISLNK(info.st_mode):
        # A staged codex home links to the real sessions dir; never size or
        # walk through it.
        return 0, info.st_mtime
    if not stat.S_ISDIR(info.st_mode):
        return info.st_size, info.st_mtime
    total = 0
    newest = info.st_mtime
    for root, _dirs, files in os.walk(path, followlinks=False):
        try:
            newest = max(newest, os.lstat(root).st_mtime)
        except OSError:
            pass
        for name in files:
            try:
                child = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            if stat.S_ISLNK(child.st_mode):
                continue
            total += child.st_size
            newest = max(newest, child.st_mtime)
    return total, newest


def _socket_absent(stderr_text):
    """True only for a socket tmux confirmed has no server.

    Anything else (permissions, protocol, a socket owned by another user) is an
    unreadable socket, never an empty one.
    """
    text = (stderr_text or "").lower()
    return "no server running" in text or "no such file or directory" in text


def live_session_names(tmux_binary="tmux"):
    """Session names on both sockets, or None when the live set is untrustworthy.

    A socket tmux confirms has no server contributes an empty set; any other
    tmux failure makes the whole answer unknown, and None is the fail-closed
    result: without a trustworthy live set nothing may be deleted.
    """
    names = set()
    for socket in ("y-agent", "default"):
        try:
            out = subprocess.run(
                [tmux_binary, "-L", socket, "list-sessions", "-F", "#{session_name}"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode != 0:
            if not _socket_absent(out.stderr.decode("utf-8", "replace")):
                return None
            continue
        names.update(n for n in out.stdout.decode("utf-8", "replace").splitlines() if n)
    return names


def _scan(run_dir):
    """({chat_id: [paths]}, [mcp dir names]) for this run dir."""
    groups = {}
    mcp_names = []
    try:
        names = os.listdir(run_dir)
    except OSError:
        return groups, mcp_names
    for name in names:
        chat_id = chat_id_for(name)
        if chat_id is not None:
            groups.setdefault(chat_id, []).append(os.path.join(run_dir, name))
        elif name.startswith(MCP_PREFIX):
            mcp_names.append(name)
    return groups, mcp_names


def path_identity(path):
    """(device, inode) of the exact object at `path`, or None when it is gone."""
    try:
        info = os.lstat(path)
    except OSError:
        return None
    return (info.st_dev, info.st_ino)


# One advisory lock per chat, shared by launch staging and every destructive
# path. The dot prefix keeps it out of the `cc-*` scan. A deletion's check and
# unlink run under the same lock the launch holds while it creates or replaces
# a generation, so no replacement can slip into the check-to-delete window.
CHAT_LOCK_PREFIX = ".cc-"
CHAT_LOCK_SUFFIX = ".lock"


def chat_lock_path(run_dir, chat_id):
    return os.path.join(run_dir, f"{CHAT_LOCK_PREFIX}{chat_id}{CHAT_LOCK_SUFFIX}")


def try_chat_lock(run_dir, chat_id):
    """Exclusive non-blocking lock fd for this chat, or None when busy/unavailable."""
    try:
        fd = os.open(chat_lock_path(run_dir, chat_id), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def release_chat_lock(fd):
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def _preserve_codex_rollouts(path):
    """Copy a staged Codex home's rollouts back before deleting the home.

    4476's app-server EXIT trap is a no-op: the tail copies the rollout to
    `$HOME/.codex/sessions` at teardown. A hard timeout, a sweeper or the
    reaper can reach the home first, so every removal copies each `*.jsonl`
    back preserving its relative path; if the copy fails the caller keeps the
    home so a later pass can retry instead of losing the only resumable copy.
    """
    src = os.path.join(path, "sessions")
    if not os.path.isdir(src) or os.path.islink(src):
        return True
    dst_root = os.path.join(
        os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex"), "sessions",
    )
    preserved = True
    for root, _dirs, files in os.walk(src, followlinks=False):
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            source = os.path.join(root, name)
            target = os.path.join(dst_root, os.path.relpath(source, src))
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(source, target)
            except OSError:
                preserved = False
    return preserved


def remove_path(path, identity):
    """Remove `path` only while it is still the observed object; bytes freed.

    Callers hold the chat lock, so a relaunch cannot create a replacement
    between this check and the unlink (todo 4487 review round 2). A staged
    Codex home is only removed after its rollouts have been copied back; a
    failed copy keeps it.
    """
    if identity is None or path_identity(path) != identity:
        return 0
    if (os.path.basename(path).endswith(".codex-home")
            and not _preserve_codex_rollouts(path)):
        return 0
    before, _newest = entry_bytes_and_mtime(path)
    try:
        if stat.S_ISDIR(os.lstat(path).st_mode):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.unlink(path)
    except OSError:
        pass
    if path_identity(path) is None:
        return before
    after, _newest = entry_bytes_and_mtime(path)
    return max(0, before - after)


def evaluate_unit_locked(run_dir, chat_id, min_age_s,
                         now=None, tmux_binary="tmux"):
    """Re-evaluate one chat's group while its lock is held (lock-authoritative).

    Re-lists the chat's `cc-<chat>*` entries and mapped `y-mcp-<hash>*` dirs,
    recomputes size/newest and device/inode identity, and re-probes the chat's
    session. A group is deletable only when this fresh, locked evaluation finds
    it non-empty, dead, and older than `min_age_s`; a live or unknown session,
    any young member, or a vanished group keeps it for a later pass. Nothing
    measured before the lock may authorize a deletion.
    """
    now = time.time() if now is None else now
    paths = []
    hashed = mcp_hash(chat_id)
    try:
        for name in os.listdir(run_dir):
            if chat_id_for(name) == chat_id:
                paths.append(os.path.join(run_dir, name))
            elif name.startswith(MCP_PREFIX) and mcp_hash_for_name(name) == hashed:
                paths.append(os.path.join(run_dir, name))
    except OSError:
        paths = []
    size = 0
    newest = 0.0
    entries = []
    for path in paths:
        identity = path_identity(path)
        if identity is None:
            continue
        part, part_newest = entry_bytes_and_mtime(path)
        size += part
        newest = max(newest, part_newest)
        entries.append((path, identity))
    unit = {
        "name": f"cc-{chat_id}",
        "chat_id": chat_id,
        "session": f"cc-{chat_id}",
        "entries": entries,
        "size": size,
        "newest": newest,
        "eligible": False,
    }
    if not entries:
        return unit
    sessions = live_session_names(tmux_binary)
    if sessions is None or f"cc-{chat_id}" in sessions:
        return unit
    unit["eligible"] = now - newest >= min_age_s
    return unit


def plan_gc(run_dir, budget_bytes=DEFAULT_BUDGET_BYTES, min_age_s=MIN_GROUP_AGE_SECONDS,
            now=None, tmux_binary="tmux"):
    """Snapshot the run dir and order deletion candidates.

    The snapshot only orders work and skips obviously busy groups; it never
    authorizes a deletion. Each chat candidate carries its id and coarse
    newest size, and `apply_gc` re-evaluates it under the chat's lock. An
    unmapped MCP directory keeps its own 24 h + identity rule because its uuid
    name is never reused by staging.
    """
    now = time.time() if now is None else now
    sessions = live_session_names(tmux_binary)
    if sessions is None:
        return {"status": "skipped", "reason": "tmux"}
    groups, mcp_names = _scan(run_dir)
    # MCP staging dirs are named by a hash of the chat id, so they can be
    # attached to their group but never reverse-mapped.
    mcp_by_hash = {}
    for name in mcp_names:
        key = mcp_hash_for_name(name)
        if key is None:
            continue
        path = os.path.join(run_dir, name)
        size, newest = entry_bytes_and_mtime(path)
        mcp_by_hash.setdefault(key, []).append((name, size, newest))

    units = []
    total = 0
    skipped_live = 0
    skipped_young = 0
    for chat_id, paths in groups.items():
        size = 0
        newest = 0.0
        for path in paths:
            part, part_newest = entry_bytes_and_mtime(path)
            size += part
            newest = max(newest, part_newest)
        staged = mcp_by_hash.pop(mcp_hash(chat_id), [])
        for _name, part, part_newest in staged:
            size += part
            newest = max(newest, part_newest)
        total += size
        live = f"cc-{chat_id}" in sessions
        young = now - newest < min_age_s
        if live:
            skipped_live += 1
        elif young:
            skipped_young += 1
        units.append({
            "name": f"cc-{chat_id}",
            "chat_id": chat_id,
            "session": f"cc-{chat_id}",
            "size": size,
            "newest": newest,
            # Coarse skip only; apply_gc re-evaluates under the lock.
            "candidate": not live and not young,
        })

    for staged in mcp_by_hash.values():
        for name, size, newest in staged:
            total += size
            path = os.path.join(run_dir, name)
            units.append({
                "name": name,
                "chat_id": None,
                "session": None,
                "entries": [(path, path_identity(path))],
                "size": size,
                "newest": newest,
                "candidate": now - newest >= UNMAPPED_MCP_MIN_AGE_SECONDS,
            })

    candidates = sorted(
        (unit for unit in units if unit["candidate"]),
        key=lambda unit: (unit["newest"], unit["name"]),
    )
    return {
        "status": "ok",
        "run_dir": run_dir,
        "tmux_binary": tmux_binary,
        "total": total,
        "candidates": candidates,
        "eligible": len(candidates),
        "skipped_live": skipped_live,
        "skipped_young": skipped_young,
        "budget": budget_bytes,
        "min_age": min_age_s,
    }


def apply_gc(plan, dry_run=False):
    """Delete candidates oldest-first until the budget is actually met.

    A chat candidate is re-evaluated under its per-chat lock: the group is
    re-listed, re-statted (newest, size, device/inode) and its session
    re-probed there, and only a dead+old result is deleted. A relaunch that
    replaced the group therefore keeps it, and a busy lock keeps it for a later
    pass. Only bytes actually removed count toward the budget, so an
    undeletable group does not stop later reclaimable ones.
    """
    if plan.get("status") != "ok":
        return plan
    sessions = live_session_names(plan["tmux_binary"])
    if sessions is None:
        return {"status": "skipped", "reason": "tmux"}
    total = plan["total"]
    freed = 0
    deleted = 0
    kept = 0
    for unit in plan["candidates"]:
        if total - freed <= plan["budget"]:
            break
        # Coarse skip only: a session already visible needs no lock.
        if unit["session"] and unit["session"] in sessions:
            kept += 1
            continue
        if unit["chat_id"]:
            kept, freed, deleted = _apply_chat_unit_locked(
                plan, unit, dry_run, kept, freed, deleted,
            )
            continue
        if dry_run:
            freed += unit["size"]
            deleted += 1
            continue
        unit_freed = 0
        remaining = 0
        for path, identity in unit["entries"]:
            unit_freed += remove_path(path, identity)
            if path_identity(path) is not None:
                remaining += 1
        freed += unit_freed
        if remaining:
            kept += 1
        else:
            deleted += 1
    return {
        "status": "ok",
        "total": total,
        "freed": freed,
        "deleted": deleted,
        "kept": kept,
        "eligible": plan["eligible"],
        "skipped_live": plan["skipped_live"],
        "skipped_young": plan["skipped_young"],
        "budget": plan["budget"],
        "dry": bool(dry_run),
    }


def _apply_chat_unit_locked(plan, unit, dry_run, kept, freed, deleted):
    """Delete one chat candidate only if its locked re-evaluation is dead+old."""
    lock_fd = try_chat_lock(plan["run_dir"], unit["chat_id"])
    if lock_fd is None:
        return kept + 1, freed, deleted
    try:
        fresh = evaluate_unit_locked(
            plan["run_dir"], unit["chat_id"], plan["min_age"],
            tmux_binary=plan["tmux_binary"],
        )
        if not fresh["eligible"] or not fresh["entries"]:
            return kept + 1, freed, deleted
        if dry_run:
            return kept, freed + fresh["size"], deleted + 1
        unit_freed = 0
        remaining = 0
        for path, identity in fresh["entries"]:
            unit_freed += remove_path(path, identity)
            if path_identity(path) is not None:
                remaining += 1
        freed += unit_freed
        if remaining:
            kept += 1
        else:
            deleted += 1
        return kept, freed, deleted
    finally:
        release_chat_lock(lock_fd)


def gc(run_dir, budget_bytes=DEFAULT_BUDGET_BYTES, min_age_s=MIN_GROUP_AGE_SECONDS,
       now=None, dry_run=False, tmux_binary="tmux"):
    """Reclaim dead+old attempt groups until the harness total is under budget."""
    return apply_gc(plan_gc(run_dir, budget_bytes, min_age_s, now, tmux_binary), dry_run)


def clean(run_dir, chat_id, before):
    """Remove one chat's staging that predates `before`.

    The monitor passes the instant its turn reached a terminal state. A new
    turn that stages the same chat's images, codex home or MCP directories
    during closeout creates newer files, so they are kept. The lock is taken
    first; mtime and device/inode are read only after it, so a replacement
    cannot arrive between the check and the removal (lock-authoritative
    eligibility). A busy lock means a launch is staging this chat right now:
    nothing is removed.
    """
    lock_fd = try_chat_lock(run_dir, chat_id)
    if lock_fd is None:
        return {"removed": 0, "kept": 0, "locked": True}
    try:
        paths = [
            os.path.join(run_dir, f"cc-{chat_id}-images"),
            os.path.join(run_dir, f"cc-{chat_id}.codex-home"),
        ]
        hashed = mcp_hash(chat_id)
        try:
            for name in os.listdir(run_dir):
                if name.startswith(MCP_PREFIX) and mcp_hash_for_name(name) == hashed:
                    paths.append(os.path.join(run_dir, name))
        except OSError:
            pass
        removed = 0
        kept = 0
        for path in paths:
            identity = path_identity(path)
            if identity is None:
                continue
            _size, newest = entry_bytes_and_mtime(path)
            if newest >= before:
                kept += 1
                continue
            remove_path(path, identity)
            if path_identity(path) is None:
                removed += 1
            else:
                kept += 1
        return {"removed": removed, "kept": kept, "locked": False}
    finally:
        release_chat_lock(lock_fd)


def clean_line(result):
    line = f"clean removed={result['removed']} kept={result['kept']}"
    return line + (" locked=1" if result.get("locked") else "")


def free_bytes(run_dir):
    """Bytes available to this user under run_dir, or None when unreadable."""
    try:
        info = os.statvfs(run_dir)
    except OSError:
        return None
    return info.f_bavail * info.f_frsize


def gc_line(result):
    if result.get("status") != "ok":
        return f"gc status={result.get('status')} reason={result.get('reason', '-')}"
    return (
        f"gc total={result['total']} freed={result['freed']} deleted={result['deleted']} "
        f"kept={result['kept']} eligible={result['eligible']} "
        f"skipped_live={result['skipped_live']} "
        f"skipped_young={result['skipped_young']} budget={result['budget']} "
        f"dry={int(result['dry'])}"
    )


def free_line(run_dir, floor_bytes):
    free = free_bytes(run_dir)
    if free is None:
        return f"free status=unreadable floor={floor_bytes}"
    status = "ok" if free >= floor_bytes else "below"
    return f"free={free} floor={floor_bytes} status={status}"


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Bound and check harness run-dir data.")
    sub = parser.add_subparsers(dest="command")

    gc_parser = sub.add_parser("gc")
    gc_parser.add_argument("--run-dir", default="/tmp")
    gc_parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET_BYTES)
    gc_parser.add_argument("--min-age", type=int, default=MIN_GROUP_AGE_SECONDS)
    gc_parser.add_argument("--tmux", default="tmux")
    gc_parser.add_argument("--floor", type=int, default=None)
    gc_parser.add_argument("--dry-run", action="store_true")

    free_parser = sub.add_parser("free")
    free_parser.add_argument("--run-dir", default="/tmp")
    free_parser.add_argument("--floor", type=int, default=DISK_FLOOR_BYTES)

    clean_parser = sub.add_parser("clean")
    clean_parser.add_argument("--run-dir", default="/tmp")
    clean_parser.add_argument("--chat", required=True)
    clean_parser.add_argument("--before", type=float, required=True)

    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "gc":
        result = gc(
            args.run_dir, args.budget, args.min_age,
            dry_run=args.dry_run, tmux_binary=args.tmux,
        )
        print(gc_line(result))
        if args.floor is not None:
            print(free_line(args.run_dir, args.floor))
        return 0
    if args.command == "free":
        line = free_line(args.run_dir, args.floor)
        print(line)
        return 0 if line.endswith("status=ok") else 1
    if args.command == "clean":
        print(clean_line(clean(args.run_dir, args.chat, args.before)))
        return 0
    parser.print_usage()
    return 2


if __name__ == "__main__":
    sys.exit(main())
