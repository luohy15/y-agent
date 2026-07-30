"""Scrape Claude Code subscription limit-window usage via the `/usage` TUI overlay.

`/usage` is a pure client-side overlay in the interactive Claude Code TUI: it
writes NOTHING to the session JSONL (spike-confirmed on CC v2.1.177), so the
only data source is `tmux capture-pane`. This module spins up a dedicated,
ephemeral `cc-usage-<rand>` tmux session on the EC2 subscription-login box, runs
`/usage`, captures the rendered pane, parses the limit windows (`Current
session`, `Current week (all models)`, and an optional third weekly window
under whatever model/promo label Anthropic currently renders there -- see
`parse_usage_pane`), then dismisses and kills the session. No LLM turn is
fired and the probe costs nothing.

This is a self-contained read path: it inlines the six pure tmux-driving
helpers (`_session` / `_prompt_file` / `_capture_pane` / `_send_keys` /
`_wait_ready` / `_tui_kill`) that used to live in the now-deleted
`claude_tui.py` (todo 2872 sub-task 2b revival; `claude_tui.py` and its
tmux-driven backend stay dead -- only these ~110 lines of terminal-driving
plumbing, with no backend logic, are restored here) plus `_with_ssh_client` /
`_ssh_exec` / `_shell_quote`, which were preserved elsewhere.
It deliberately does NOT paste a prompt or trigger a real LLM turn, and does
NOT touch the `claude -p` path.

Every remote command this module runs explicitly `unset`s the relay env vars
first (`_ANTHROPIC_ENV_UNSET`) rather than relying on the SSH session's own
environment already being clean: tmux `new-session` on an already-running
server inherits that SERVER's original startup environment, not the env of
whatever process invokes `new-session` (verified empirically, todo 2872
sub-task 2b, against a shared tmux server on this box that was first started
by a relay-launch carrying `ANTHROPIC_*` exports -- an outer `env -u ...`
prefix on the `tmux new-session` command had no effect for exactly that
reason). The explicit unset is what makes a session here read the
subscription grant instead of the relay identity, and what keeps a
concurrently running relay-backed agent turn untouched.
"""

import asyncio
import json
import re
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional

from loguru import logger

from agent.claude_code import _shell_quote, _ssh_exec
from agent.detach import _with_ssh_client


# Bound on the fresh-launch dialog dismissal / readiness wait.
READY_TIMEOUT_SECONDS = 90
# Footer that the TUI shows once it is idle and ready for input.
READY_FOOTER = "bypass permissions on"
# Bound on the wait for the `/usage` overlay to render after submitting.
USAGE_TIMEOUT_SECONDS = 20
# Prefix every remote command with this so it never inherits the shared tmux
# server's relay env (see module docstring).
_ANTHROPIC_ENV_UNSET = (
    "unset ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN ANTHROPIC_API_KEY "
    "_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL"
)


# ---------------------------------------------------------------------------
# tmux / TUI driving helpers (inlined from the deleted claude_tui.py --
# pure terminal plumbing, no backend logic; see module docstring)
#
# Every helper here takes a `run(cmd: str) -> str` callable instead of a raw
# SSH client, so the identical scrape core (`_scrape_session` below) can
# drive tmux either over SSH (`_run_ssh`, used when the caller is a
# different host than the one that owns the subscription grant) or as a
# plain local subprocess (`_run_local`, used by `read_claude_usage_local`
# when the caller -- e.g. `y usage limits` on the VM itself -- IS already
# that host, so an SSH hop back to itself would be a pointless loopback).
# ---------------------------------------------------------------------------

def _session(chat_id: str) -> str:
    return f"cc-{chat_id}"


def _prompt_file(chat_id: str) -> str:
    return f"/tmp/cc-{chat_id}.prompt"


def _run_ssh(client) -> Callable[[str], str]:
    return lambda cmd: _ssh_exec(client, cmd)


def _run_local(cmd: str) -> str:
    """Run a shell command as a plain local subprocess (no SSH) and return
    stdout, raising the same way `_ssh_exec` does on a genuine non-zero exit
    -- but tolerating tmux's own benign "no server running" / "session not
    found" errors, which show up routinely on stale-cleanup and kill calls."""
    result = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True)
    if result.returncode != 0:
        err = result.stderr
        if "no server running" not in err and "session not found" not in err:
            raise RuntimeError(f"local command failed (exit {result.returncode}): {err}")
    return result.stdout


def _capture_pane(run: Callable[[str], str], chat_id: str) -> str:
    try:
        return run(f"tmux capture-pane -p -t {_shell_quote(_session(chat_id))} 2>/dev/null")
    except Exception:
        return ""


def _send_keys(run: Callable[[str], str], chat_id: str, *keys: str) -> None:
    target = _shell_quote(_session(chat_id))
    for key in keys:
        try:
            run(f"tmux send-keys -t {target} {key}")
        except Exception:
            pass


def _tui_kill(run: Callable[[str], str], chat_id: str) -> None:
    """Stop the current turn (Escape) and tear down the tmux session."""
    try:
        run(f"tmux send-keys -t {_shell_quote(_session(chat_id))} Escape 2>/dev/null")
    except Exception:
        pass
    try:
        run(f"tmux kill-session -t {_shell_quote(_session(chat_id))} 2>/dev/null")
        run(f"rm -f {_shell_quote(_prompt_file(chat_id))} 2>/dev/null")
    except Exception:
        pass


async def _wait_ready(run: Callable[[str], str], chat_id: str, dismiss_dialogs: bool, timeout: int = READY_TIMEOUT_SECONDS) -> bool:
    """Poll capture-pane until the ready footer appears, dismissing fresh-launch
    dialogs on the way. Returns True if the TUI reached the ready prompt.

    Fresh untrusted-folder launch shows up to three dialogs in order:
      1. folder-trust  -> Enter (default item 1 = trust)
      2. bypass-permissions warning -> Down, Enter (item 2 = accept)
      3. fullscreen-renderer upsell -> Down, Enter (pick "Not now")
    A resume / trusted-folder launch goes straight to the footer. A logged-out
    box never reaches the footer at all -- the caller degrades to
    `parse_ok=False` on a timeout here rather than raising (see
    `read_claude_usage`).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pane = _capture_pane(run, chat_id)
        lower = pane.lower()

        if READY_FOOTER in lower:
            return True

        if dismiss_dialogs:
            if ("do you trust" in lower or "trust the files" in lower
                    or "project you created" in lower):
                _send_keys(run, chat_id, "Enter")
            elif "yes, i accept" in lower or "no, exit" in lower:
                # Bypass-permissions warning: default is "No, exit"; move to accept.
                _send_keys(run, chat_id, "Down", "Enter")
            elif "fullscreen" in lower:
                _send_keys(run, chat_id, "Down", "Enter")

        await asyncio.sleep(1)

    logger.warning("claude_usage: ready footer not seen within {}s for chat {}", timeout, chat_id)
    return False


# ---------------------------------------------------------------------------
# Pure parser (sub-task 1)
# ---------------------------------------------------------------------------

_SESSION_LABEL = "Current session"
_WEEK_ALL_LABEL = "Current week (all models)"
# A third, account/promo-dependent weekly window keyed by whatever qualifier
# the overlay currently shows in parens. Re-verified live on 2026-07-30
# (sub-task 2b): the label is NOT stable text -- the 2.1.177 fixture recorded
# "Current week (Sonnet only)", but on 2.1.220 (with the Fable 5 promo active
# on this account) it renders "Current week (Fable)" instead. Anthropic
# renames this per active model/promo, so match generically on the paren
# qualifier rather than pinning a specific model name, and carry the observed
# label through so a caller can build a stable key from it.
_WEEK_EXTRA_RE = re.compile(r"Current week \(([^)]+)\)")

_PERCENT_RE = re.compile(r"(\d+)%\s+used")
_RESET_RE = re.compile(r"Resets\s+(.+)")


def _scan_window(lines: list, idx: int) -> tuple:
    """Scan the label line plus the next 3 lines for a `N% used` percent and
    a `Resets ...` string (they sit on the bar line and the line below it,
    independent of the block-character bar, and tolerate an extra promo line
    like "+50% weekly limits promo through Aug 19" sharing the window)."""
    percent: Optional[int] = None
    reset: Optional[str] = None
    for line in lines[idx:idx + 4]:
        if percent is None:
            m = _PERCENT_RE.search(line)
            if m:
                percent = int(m.group(1))
        if reset is None:
            m = _RESET_RE.search(line)
            if m:
                reset = m.group(1).strip()
    return percent, reset


def parse_usage_pane(text: str) -> Dict:
    """Parse the `/usage` overlay pane text into the limit windows.

    Returns:

        {
          "session":    {"percent": int, "reset": str|None} | None,
          "week_all":   {"percent": int, "reset": str|None} | None,
          "week_extra": {"label": str, "percent": int, "reset": str|None} | None,
          "parse_ok":   bool,   # True when session + week_all percents parsed
          "raw":        str,    # the verbatim pane, for fallback display
        }

    `parse_ok` keys on `session` + `week_all` (the two always-rendered, alert-
    relevant windows); `week_extra` is optional because the overlay only
    renders a third window for some accounts/promos, and under a different
    label depending which one (see `_WEEK_EXTRA_RE`). `parse_ok=False` keeps
    `raw` populated so a caller can surface the raw pane instead of silently
    reporting 0% if a future CC version renames labels again.
    """
    result: Dict = {
        "session": None,
        "week_all": None,
        "week_extra": None,
        "parse_ok": False,
        "raw": text,
    }

    lines = text.splitlines()

    idx = next((i for i, line in enumerate(lines) if _SESSION_LABEL in line), None)
    if idx is not None:
        percent, reset = _scan_window(lines, idx)
        if percent is not None:
            result["session"] = {"percent": percent, "reset": reset}

    idx = next((i for i, line in enumerate(lines) if _WEEK_ALL_LABEL in line), None)
    if idx is not None:
        percent, reset = _scan_window(lines, idx)
        if percent is not None:
            result["week_all"] = {"percent": percent, "reset": reset}

    idx = None
    label = None
    for i, line in enumerate(lines):
        m = _WEEK_EXTRA_RE.search(line)
        if m and m.group(1) != "all models":
            idx, label = i, m.group(1)
            break
    if idx is not None:
        percent, reset = _scan_window(lines, idx)
        if percent is not None:
            result["week_extra"] = {"label": label, "percent": percent, "reset": reset}

    result["parse_ok"] = result["session"] is not None and result["week_all"] is not None
    return result


# ---------------------------------------------------------------------------
# Ephemeral scrape core (sub-task 2; local execution added sub-task 3)
# ---------------------------------------------------------------------------

async def _scrape_session(
    run: Callable[[str], str],
    chat_id: str,
    cwd: Optional[str],
    timeout: int,
    ready_timeout: int,
) -> tuple:
    """Drive one ephemeral `/usage` scrape through `run` (SSH or local exec)
    and return `(pane_text, ready)`. `run`-agnostic: the launch/wait/poll
    sequence is identical whether `run` executes over SSH or as a local
    subprocess, so this is the single source of truth for both
    `read_claude_usage` and `read_claude_usage_local`. The caller owns
    tearing the session down (`_tui_kill`) in a `finally`."""
    session_name = _session(chat_id)
    cmd = ["claude", "--permission-mode", "bypassPermissions"]
    pane = ""
    ready = False

    # Stale cleanup, then validate cwd (fall back to no -c on a miss).
    run(
        f"tmux kill-session -t {_shell_quote(session_name)} 2>/dev/null; "
        f"rm -f {_shell_quote(_prompt_file(chat_id))} 2>/dev/null",
    )
    if cwd:
        exists = run(f"test -d {_shell_quote(cwd)} && echo ok || echo missing").strip() == "ok"
        if not exists:
            cwd = None

    # Assemble the inner command: keep EC2 awake, cd, unset any relay env,
    # exec the TUI. The explicit unset is required (not merely relying on
    # the caller's own environment already being clean) because tmux
    # new-session on an already-running server inherits that server's
    # ORIGINAL startup environment, not the environment of whatever process
    # invokes `tmux new-session` -- verified empirically (todo 2872 sub-task
    # 2b) against this box's shared tmux server, which was first started by
    # a relay-launch carrying ANTHROPIC_* exports.
    inner_parts = [
        _ANTHROPIC_ENV_UNSET + ";",
        "( while :; do date +%s > /tmp/ec2-ssh-last-seen; sleep 60; done ) &",
    ]
    if cwd:
        inner_parts.append(f"cd {_shell_quote(cwd)} &&")
    inner_parts.append("exec " + " ".join(_shell_quote(c) for c in cmd))
    inner = " ".join(inner_parts)

    # Tall pane: the `/usage` overlay renders the windows block (`Current
    # session` / `Current week`) at the TOP followed by a `What's
    # contributing` breakdown + footer. With a short pane the whole dialog
    # exceeds the viewport and the windows block scrolls off the top, so
    # `capture-pane -p` (visible region only) grabs just the lower section.
    # Give the TUI plenty of rows so the entire overlay fits and the windows
    # block stays in the captured region.
    tmux_cmd = (
        f"tmux new-session -d -s {_shell_quote(session_name)} -x 220 -y 80 "
        + (f"-c {_shell_quote(cwd)} " if cwd else "")
        + _shell_quote(inner)
    )
    run(tmux_cmd)

    # Wait for the ready footer, dismissing first-launch dialogs (belt and
    # suspenders even in a trusted folder). A logged-out box (no
    # subscription grant) never reaches it -- capture whatever is on screen
    # and degrade below rather than hang or raise.
    ready = await _wait_ready(run, chat_id, dismiss_dialogs=True, timeout=ready_timeout)
    if not ready:
        pane = _capture_pane(run, chat_id)
    else:
        # Type `/usage` literally (slash-command autocomplete) and submit.
        target = _shell_quote(session_name)
        run(f"tmux send-keys -t {target} -l {_shell_quote('/usage')}")
        time.sleep(0.5)
        _send_keys(run, chat_id, "Enter")

        # Poll until the overlay renders (a window label + a `% used` line).
        # The full overlay is taller than the pane, so the windows block
        # (`Current session` / `Current week`) scrolls off the top into tmux
        # scrollback while the visible region shows only the lower "What's
        # contributing" breakdown + footer. Capture the whole scrollback
        # (`-S -`) so the windows block is always included.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pane = run(f"tmux capture-pane -p -S - -t {target} 2>/dev/null")
            if "Current session" in pane and "% used" in pane:
                break
            await asyncio.sleep(1)

        # Dismiss the overlay (Escape) before tearing down.
        _send_keys(run, chat_id, "Escape")

    return pane, ready


async def read_claude_usage(
    vm_config,
    *,
    timeout: int = USAGE_TIMEOUT_SECONDS,
    ready_timeout: int = READY_TIMEOUT_SECONDS,
) -> Dict:
    """Launch an ephemeral Claude Code TUI over SSH, run `/usage`, parse +
    return the limit windows. Always tears the tmux session down in a
    `finally`. For a caller that is already executing ON the subscription
    box (e.g. `y usage limits`), prefer `read_claude_usage_local` instead --
    this SSH variant is for a caller on a *different* host.

    Returns the `parse_usage_pane` dict (the three windows + `parse_ok` +
    `raw`) plus `"ready": bool` -- whether the TUI ever reached the ready
    footer. A box with no subscription grant (or any other stuck launch)
    never reaches ready; that degrades to `ready=False, parse_ok=False` with
    whatever was on screen captured into `raw` instead of hanging or raising
    -- a dark card, never a guessed number.
    """
    chat_id = f"usage-{uuid.uuid4().hex[:8]}"  # -> tmux session `cc-usage-<rand>`

    with _with_ssh_client(vm_config) as client:
        run = _run_ssh(client)
        try:
            cwd = vm_config.work_dir if vm_config else None
            pane, ready = await _scrape_session(run, chat_id, cwd, timeout, ready_timeout)
        finally:
            _tui_kill(run, chat_id)

    parsed = parse_usage_pane(pane)
    parsed["ready"] = ready
    if not parsed["parse_ok"]:
        logger.warning("read_claude_usage: parse_ok=False (ready={}); raw pane:\n{}", ready, pane)
    return parsed


async def read_claude_usage_local(
    *,
    work_dir: Optional[str] = None,
    timeout: int = USAGE_TIMEOUT_SECONDS,
    ready_timeout: int = READY_TIMEOUT_SECONDS,
) -> Dict:
    """Local-execution twin of `read_claude_usage`: drives the identical
    `/usage` scrape (`_scrape_session`) via a plain local subprocess instead
    of SSH. `y usage limits` always runs ON the subscription box itself
    (todo 2872's settled execution model), so `read_claude_usage(vm_config)`
    would SSH the box back into itself for no reason; this is the reader
    that command actually wants. Same return shape as `read_claude_usage`.
    """
    chat_id = f"usage-{uuid.uuid4().hex[:8]}"
    try:
        pane, ready = await _scrape_session(_run_local, chat_id, work_dir, timeout, ready_timeout)
    finally:
        _tui_kill(_run_local, chat_id)

    parsed = parse_usage_pane(pane)
    parsed["ready"] = ready
    if not parsed["parse_ok"]:
        logger.warning("read_claude_usage_local: parse_ok=False (ready={}); raw pane:\n{}", ready, pane)
    return parsed


# ---------------------------------------------------------------------------
# Cheap logged-in check (sub-task 3): lets the `claude_tui_usage` reader
# skip the several-seconds-long scrape entirely when the box is definitely
# logged out, and (via the scrape's own `ready` flag on a full attempt)
# distinguishes `reauth_required` from a label-drift `parse_failed` that a
# bare `parse_ok=False` cannot make on its own.
# ---------------------------------------------------------------------------

async def read_claude_login_status(vm_config) -> Optional[bool]:
    """SSH variant of the cheap `claude auth status --json` check. Prefer
    `read_claude_login_status_local` when already running on the
    subscription box (see `read_claude_usage_local`).

    Returns True/False for a definite answer, or None if the check itself
    failed (SSH/parse trouble) -- callers should fall back to the full
    scrape rather than assume either state on None.
    """
    with _with_ssh_client(vm_config) as client:
        try:
            out = _ssh_exec(
                client,
                f"{_ANTHROPIC_ENV_UNSET}; claude auth status --json 2>/dev/null; true",
            )
        except Exception as e:
            logger.warning("read_claude_login_status: SSH check failed: {}", e)
            return None
    return _parse_login_status(out)


async def read_claude_login_status_local() -> Optional[bool]:
    """Local-execution twin of `read_claude_login_status` -- no SSH hop,
    for a caller (e.g. `y usage limits`) already running on the box."""
    try:
        out = _run_local(f"{_ANTHROPIC_ENV_UNSET}; claude auth status --json 2>/dev/null; true")
    except Exception as e:
        logger.warning("read_claude_login_status_local: local check failed: {}", e)
        return None
    return _parse_login_status(out)


def _parse_login_status(out: str) -> Optional[bool]:
    try:
        return bool(json.loads(out).get("loggedIn"))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Reset-string -> absolute timestamp, and a stable extra-window key
# (sub-task 3: the API contract needs a real `reset_at`, and Anthropic
# renames the third weekly window's label per active model/promo, see
# `_WEEK_EXTRA_RE`)
# ---------------------------------------------------------------------------

_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "Aug 5, 9am (UTC)" / "Jun 17, 8:59am (UTC)"
_RESET_DATE_TIME_RE = re.compile(
    r"^([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*\(UTC\)$", re.IGNORECASE
)
# "4:59am (UTC)" / "5am (UTC)" -- no date, implying the next occurrence.
_RESET_TIME_ONLY_RE = re.compile(
    r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*\(UTC\)$", re.IGNORECASE
)


def reset_at_iso(reset: Optional[str], now: Optional[datetime] = None) -> Optional[str]:
    """Parse the `/usage` overlay's localized `Resets ...` text (2515
    deferred this; the `--json` envelope needs a real `reset_at`) into an
    absolute UTC ISO8601 timestamp. Two observed shapes, both anchored to
    "now" since the overlay never prints a year: a bare time (next
    occurrence, rolling to tomorrow if already past today) and a month/day +
    time (this year, rolling to next year if the resulting date is already
    more than a day in the past -- i.e. this reset already happened and
    Anthropic is describing next year's). Anything else is left unparsed
    (`None`) rather than guessed -- a caller must never fabricate a reset
    time from text this parser doesn't recognize.
    """
    if not reset:
        return None
    now = now or datetime.now(timezone.utc)
    text = reset.strip()

    m = _RESET_DATE_TIME_RE.match(text)
    if m:
        month_name, day, hour, minute, meridiem = m.groups()
        month = _MONTH_ABBR.get(month_name.lower()[:3])
        if month is None:
            return None
        try:
            candidate = datetime(
                now.year, month, int(day), _hour_24(hour, meridiem), int(minute or 0),
                tzinfo=timezone.utc,
            )
        except ValueError:
            return None
        if candidate < now - timedelta(days=1):
            candidate = candidate.replace(year=now.year + 1)
        return candidate.isoformat().replace("+00:00", "Z")

    m = _RESET_TIME_ONLY_RE.match(text)
    if m:
        hour, minute, meridiem = m.groups()
        candidate = now.replace(
            hour=_hour_24(hour, meridiem), minute=int(minute or 0), second=0, microsecond=0
        )
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate.isoformat().replace("+00:00", "Z")

    return None


def _hour_24(hour: str, meridiem: str) -> int:
    h = int(hour) % 12
    return h + 12 if meridiem.lower() == "pm" else h


def extra_window_key(label: str) -> str:
    """Build a stable `extra_windows` key from the observed third-window
    label (e.g. "Fable" -> "one_week_fable", "Sonnet only" ->
    "one_week_sonnet_only") instead of hardcoding a single model name --
    Anthropic renames this window per active model/promo (see
    `_WEEK_EXTRA_RE` / sub-task 2b's live re-verification)."""
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return f"one_week_{slug}" if slug else "one_week_extra"
