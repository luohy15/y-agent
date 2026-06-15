"""Scrape Claude Code subscription limit-window usage via the `/usage` TUI overlay.

`/usage` is a pure client-side overlay in the interactive Claude Code TUI: it
writes NOTHING to the session JSONL (spike-confirmed on CC v2.1.177), so the
only data source is `tmux capture-pane`. This module spins up a dedicated,
ephemeral `cc-usage-<rand>` tmux session on the EC2 subscription-login box, runs
`/usage`, captures the rendered pane, parses the three limit windows
(`Current session` / `Current week (all models)` / `Current week (Sonnet only)`),
then dismisses and kills the session. No LLM turn is fired and the probe costs
nothing.

This is a NEW, self-contained read path. It reuses only the pure low-level tmux
helpers from `claude_tui` (`_session` / `_send_keys` / `_wait_ready` /
`_tui_kill`) and `_with_ssh_client` / `_ssh_exec` / `_shell_quote`.
It deliberately does NOT call `start_detached_claude_tui_ssh` (which pastes a
prompt and would trigger a real LLM turn) and does NOT touch the `claude -p`
path.
"""

import asyncio
import re
import time
import uuid
from typing import Dict, Optional

from loguru import logger

from agent.claude_code import _shell_quote, _ssh_exec
from agent.detach import _with_ssh_client
from agent.claude_tui import (
    READY_TIMEOUT_SECONDS,
    _prompt_file,
    _send_keys,
    _session,
    _tui_kill,
    _wait_ready,
)


# Bound on the wait for the `/usage` overlay to render after submitting.
USAGE_TIMEOUT_SECONDS = 20


# ---------------------------------------------------------------------------
# Pure parser (sub-task 1)
# ---------------------------------------------------------------------------

# (result-key, pane label) for the three limit windows the overlay renders.
_WINDOW_LABELS = (
    ("session", "Current session"),
    ("week_all", "Current week (all models)"),
    ("week_sonnet", "Current week (Sonnet only)"),
)

_PERCENT_RE = re.compile(r"(\d+)%\s+used")
_RESET_RE = re.compile(r"Resets\s+(.+)")


def parse_usage_pane(text: str) -> Dict:
    """Parse the `/usage` overlay pane text into the three limit windows.

    For each window label, scan that line plus the next 3 lines for a
    `N% used` percent and a `Resets ...` string (they sit on the bar line and
    the line below it, independent of the block-character bar). Returns:

        {
          "session":     {"percent": int, "reset": str|None} | None,
          "week_all":    {"percent": int, "reset": str|None} | None,
          "week_sonnet": {"percent": int, "reset": str|None} | None,
          "parse_ok":    bool,   # True when session + week_all percents parsed
          "raw":         str,    # the verbatim pane, for fallback display
        }

    `parse_ok` keys on `session` + `week_all` (the two always-rendered, alert-
    relevant windows); `week_sonnet` is optional because the overlay only renders
    it for some accounts/versions. `parse_ok=False` keeps `raw` populated so a
    caller can surface the raw pane instead of silently reporting 0% if a future
    CC version renames labels.
    """
    result: Dict = {
        "session": None,
        "week_all": None,
        "week_sonnet": None,
        "parse_ok": False,
        "raw": text,
    }

    lines = text.splitlines()
    for key, label in _WINDOW_LABELS:
        idx = next((i for i, line in enumerate(lines) if label in line), None)
        if idx is None:
            continue

        percent: Optional[int] = None
        reset: Optional[str] = None
        # Scan the label line plus the next 3 lines.
        for line in lines[idx:idx + 4]:
            if percent is None:
                m = _PERCENT_RE.search(line)
                if m:
                    percent = int(m.group(1))
            if reset is None:
                m = _RESET_RE.search(line)
                if m:
                    reset = m.group(1).strip()
        if percent is not None:
            result[key] = {"percent": percent, "reset": reset}

    result["parse_ok"] = result["session"] is not None and result["week_all"] is not None
    return result


# ---------------------------------------------------------------------------
# Ephemeral scrape core (sub-task 2)
# ---------------------------------------------------------------------------

async def read_claude_usage(
    vm_config,
    *,
    timeout: int = USAGE_TIMEOUT_SECONDS,
    ready_timeout: int = READY_TIMEOUT_SECONDS,
) -> Dict:
    """Launch an ephemeral Claude Code TUI, run `/usage`, parse + return the
    limit windows. Always tears the tmux session down in a `finally`.

    Returns the `parse_usage_pane` dict (the three windows + `parse_ok` + `raw`).
    Raises `RuntimeError` if the TUI never reaches the ready footer.
    """
    chat_id = f"usage-{uuid.uuid4().hex[:8]}"  # -> tmux session `cc-usage-<rand>`
    session_name = _session(chat_id)
    cmd = ["claude", "--permission-mode", "bypassPermissions"]
    pane = ""

    with _with_ssh_client(vm_config) as client:
        try:
            cwd = vm_config.work_dir if vm_config else None

            # Stale cleanup, then validate cwd (fall back to no -c on a miss).
            _ssh_exec(
                client,
                f"tmux kill-session -t {_shell_quote(session_name)} 2>/dev/null; "
                f"rm -f {_shell_quote(_prompt_file(chat_id))} 2>/dev/null",
            )
            if cwd:
                exists = _ssh_exec(
                    client, f"test -d {_shell_quote(cwd)} && echo ok || echo missing"
                ).strip() == "ok"
                if not exists:
                    cwd = None

            # Assemble the inner command: keep EC2 awake, cd, exec the TUI.
            inner_parts = [
                "( while :; do date +%s > /tmp/ec2-ssh-last-seen; sleep 60; done ) &",
            ]
            if cwd:
                inner_parts.append(f"cd {_shell_quote(cwd)} &&")
            inner_parts.append("exec " + " ".join(_shell_quote(c) for c in cmd))
            inner = " ".join(inner_parts)

            # Tall pane: the `/usage` overlay renders the windows block
            # (`Current session` / `Current week`) at the TOP followed by a
            # `What's contributing` breakdown + footer. With a short pane the
            # whole dialog exceeds the viewport and the windows block scrolls
            # off the top, so `capture-pane -p` (visible region only) grabs just
            # the lower section. Give the TUI plenty of rows so the entire
            # overlay fits and the windows block stays in the captured region.
            tmux_cmd = (
                f"tmux new-session -d -s {_shell_quote(session_name)} -x 220 -y 80 "
                + (f"-c {_shell_quote(cwd)} " if cwd else "")
                + _shell_quote(inner)
            )
            _ssh_exec(client, tmux_cmd)

            # Wait for the ready footer, dismissing first-launch dialogs (belt
            # and suspenders even in a trusted folder).
            if not await _wait_ready(client, chat_id, dismiss_dialogs=True, timeout=ready_timeout):
                raise RuntimeError("Claude Code TUI did not reach ready state for /usage scrape")

            # Type `/usage` literally (slash-command autocomplete) and submit.
            target = _shell_quote(session_name)
            _ssh_exec(client, f"tmux send-keys -t {target} -l {_shell_quote('/usage')}")
            time.sleep(0.5)
            _send_keys(client, chat_id, "Enter")

            # Poll until the overlay renders (a window label + a `% used` line).
            # The full overlay is taller than the pane, so the windows block
            # (`Current session` / `Current week`) scrolls off the top into
            # tmux scrollback while the visible region shows only the lower
            # `What's contributing` breakdown + footer. Capture the whole
            # scrollback (`-S -`) so the windows block is always included.
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                pane = _ssh_exec(
                    client, f"tmux capture-pane -p -S - -t {target} 2>/dev/null"
                )
                if "Current session" in pane and "% used" in pane:
                    break
                await asyncio.sleep(1)

            # Dismiss the overlay (Escape) before tearing down.
            _send_keys(client, chat_id, "Escape")
        finally:
            _tui_kill(client, chat_id)

    parsed = parse_usage_pane(pane)
    if not parsed["parse_ok"]:
        logger.warning("read_claude_usage: parse_ok=False; raw pane:\n{}", pane)
    return parsed
