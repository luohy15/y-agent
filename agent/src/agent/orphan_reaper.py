"""Reap leaked detached-session wrappers left behind after `tmux kill-session`.

This file's source is sent to the VM and run as `python3 -c <source> <min_age_s>
<stdin_prefix>` (see `detach._reap_orphan_wrappers_cmd`), so it must stay
stdlib-only, import-free of `agent`, and Python 3.9 compatible.

A target is a process owned by this UID that is its own session and process
group leader, whose argv is exactly `<shell> -c <inner>` where `<inner>` starts
with the detach heartbeat prefix and pipes `tail -f -n +1 '<stdin_prefix>*.stdin'`,
that is not a live tmux pane, and that is at least `min_age_s` old. Pane
enumeration happens after the candidate scan, and any tmux failure reaps
nothing (fail closed). Every signal is sent to a single PID only after its start
time and UID are re-read and still match, so PID reuse cannot redirect it. The
wrapper shells (the leader and its forked subshells, which share its argv) are
KILLed first: a legacy `trap ... EXIT HUP INT TERM` wrapper would otherwise run
its chat-scoped cleanup on TERM and continue to write `.exit`, contaminating
that chat's next turn. The rest of the tree (process group, session, and ppid
descendants) is TERMed, then anything still alive after the grace period is
KILLed. The session/descendant reach also covers a `nohup` daemon started
inside a leaked turn, since it shares the wrapper's session.

Prints one line: `reaped=<targets> survivors=<pids>` or `reaped=0 skipped=<why>`.
"""

import os
import re
import signal
import subprocess
import sys
import time

# Must equal the first inner_parts of detach._start_detached_tmux (pinned by test).
WRAPPER_PREFIX = (
    "date +%s > /tmp/ec2-ssh-last-seen; "
    "( while :; do date +%s > /tmp/ec2-ssh-last-seen; sleep 60; done ) & "
    "HEARTBEAT_PID=$!;"
)


def _read_proc(pid):
    """Return (ppid, pgrp, sid, start, uid, argv) or None if gone/unreadable."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            stat = f.read()
        with open(f"/proc/{pid}/status") as f:
            uid = next(int(line.split()[1]) for line in f if line.startswith("Uid:"))
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read()
    except (OSError, StopIteration, ValueError, IndexError):
        return None
    fields = stat[stat.rfind(")") + 2:].split()
    argv = [a.decode("utf-8", "replace") for a in raw.split(b"\0")[:-1]]
    return int(fields[1]), int(fields[2]), int(fields[3]), int(fields[19]), uid, argv


def _snapshot():
    procs = {}
    for name in os.listdir("/proc"):
        if name.isdigit():
            info = _read_proc(int(name))
            if info is not None:
                procs[int(name)] = info
    return procs


def is_wrapper(argv, stdin_prefix):
    if len(argv) != 3 or argv[1] != "-c" or not argv[0].endswith("sh"):
        return False
    inner = argv[2]
    stdin_re = r"tail -f -n \+1 '" + re.escape(stdin_prefix) + r"[A-Za-z0-9_.-]*\.stdin' \|"
    return inner.startswith(WRAPPER_PREFIX) and re.search(stdin_re, inner) is not None


def live_pane_pids():
    """PIDs of every live tmux pane, or None when tmux cannot be enumerated."""
    try:
        out = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{pane_pid}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        return {int(line) for line in out.stdout.decode().split()}
    except ValueError:
        return None


def _tree(procs, leader, uid):
    """(pid, start) for every same-UID process in leader's group, session or descendants."""
    members = {p for p, i in procs.items() if i[4] == uid and (i[1] == leader or i[2] == leader)}
    members.add(leader)
    grew = True
    while grew:
        children = {p for p, i in procs.items() if i[4] == uid and i[0] in members} - members
        members |= children
        grew = bool(children)
    return {(p, procs[p][3]) for p in members if p in procs}


def signal_if_same(pid, start, uid, sig):
    """Signal pid only if it is still the same process (start time and UID)."""
    info = _read_proc(pid)
    if info is None or info[3] != start or info[4] != uid:
        return False
    try:
        os.kill(pid, sig)
    except OSError:
        return False
    return True


def reap(min_age_s, stdin_prefix, grace_s=5.0):
    uid = os.getuid()
    hz = os.sysconf("SC_CLK_TCK")
    procs = _snapshot()
    with open("/proc/uptime") as f:
        uptime = float(f.read().split()[0])
    candidates = {
        pid: info[3] for pid, info in procs.items()
        if info[4] == uid and pid == info[1] == info[2]
        and uptime - info[3] / hz >= min_age_s
        and is_wrapper(info[5], stdin_prefix)
    }
    if not candidates:
        return "reaped=0"
    panes = live_pane_pids()
    if panes is None:
        return "reaped=0 skipped=tmux"
    targets = {pid: start for pid, start in candidates.items() if pid not in panes}
    if not targets:
        return "reaped=0"

    def alive_members():
        now = _snapshot()
        found = set()
        for leader, start in targets.items():
            current = now.get(leader)
            if current is not None and current[3] != start:
                continue  # leader PID reused: this group is no longer ours
            found |= _tree(now, leader, uid)
        return found

    members, shells = set(), set()
    for leader in targets:
        tree = _tree(procs, leader, uid)
        members |= tree
        shells |= {m for m in tree if procs[m[0]][5] == procs[leader][5]}
    for pid, start in shells:
        signal_if_same(pid, start, uid, signal.SIGKILL)
    for pid, start in members - shells:
        signal_if_same(pid, start, uid, signal.SIGTERM)
    deadline = time.monotonic() + grace_s
    remaining = alive_members()
    while remaining and time.monotonic() < deadline:
        time.sleep(0.2)
        remaining = alive_members()
    for _ in range(3):
        if not remaining:
            break
        for pid, start in remaining:
            signal_if_same(pid, start, uid, signal.SIGKILL)
        time.sleep(0.2)
        remaining = alive_members()
    survivors = ",".join(str(p) for p, _ in sorted(remaining)) or "-"
    return f"reaped={len(targets)} survivors={survivors}"


if __name__ == "__main__":
    print(reap(float(sys.argv[1]), sys.argv[2]))
