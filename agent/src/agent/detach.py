"""Shared helpers for detached tmux-based execution over SSH.

`start_detached_ssh` (claude_code) and `start_detached_codex_ssh` (codex)
share almost identical skeletons: SSH connect/teardown, stale cleanup, tmux
wrap, and an initial stdout sniff to extract a session/thread id. This module
extracts those shared steps and exposes a small `DetachBackendSpec` for the
three hooks that do differ (per-backend setup, exec command assembly, initial
id parsing).

`tail_*_output` helpers intentionally keep their inline SSH bookkeeping; this
refactor is scoped to the start_* path.
"""

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from agent.claude_code import (
    _parse_ssh_target,
    _shell_quote,
    _ssh_exec,
    parse_stream_line,
)


@contextmanager
def _with_ssh_client(vm_config, ssh_client=None):
    """Yield a paramiko SSHClient, connecting from `vm_config` if not passed.

    If the caller supplies `ssh_client` (from a pool), it is reused and left
    open. Otherwise a fresh connection is opened and closed on exit.
    """
    owns_client = ssh_client is None
    if owns_client:
        import io
        import paramiko

        user, host, port = _parse_ssh_target(vm_config.vm_name)
        key = paramiko.Ed25519Key.from_private_key(io.StringIO(vm_config.api_token))

        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(host, port=port, username=user, pkey=key)

    try:
        yield ssh_client
    finally:
        if owns_client:
            ssh_client.close()


@dataclass
class DetachBackendSpec:
    """Per-backend hooks for `_start_detached_tmux`.

    - `setup(client, chat_id, prompt)` — optional, runs after stale cleanup
      and before the tmux command is assembled (e.g. write a stream-json
      stdin file via SFTP).
    - `build_exec(cmd, chat_id, prompt) -> str` — the exec command string that
      goes between the `cd` clause and the stdout/stderr redirect.
    - `parse_initial(obj) -> Optional[str]` — inspect a parsed stream-json
      event from the first few stdout lines and return the session/thread id
      if this event carries it; return None to keep scanning.
    """

    build_exec: Callable[[List[str], str, str], str]
    parse_initial: Callable[[Dict], Optional[str]]
    setup: Optional[Callable[[object, str, str], None]] = None


async def _start_detached_tmux(
    cmd: List[str],
    prompt: str,
    cwd: Optional[str],
    chat_id: str,
    vm_config,
    spec: DetachBackendSpec,
    env: Optional[Dict[str, str]] = None,
    ssh_client=None,
) -> Optional[str]:
    """Shared skeleton for starting a detached tmux session over SSH.

    Steps:
      1. Kill any stale `cc-<chat_id>` tmux session and remove leftover
         stdin/exit files.
      2. Run backend-specific `spec.setup` (optional).
      3. Build the tmux inner command: last-seen touch, env exports,
         optional `cd`, backend exec (from `spec.build_exec`), stdout/stderr
         redirect, and exit-code capture.
      4. Launch `tmux new-session -d -s cc-<chat_id> <inner>`.
      5. Sleep briefly, read the first few stdout lines, and extract the
         initial id via `spec.parse_initial`.
    """
    with _with_ssh_client(vm_config, ssh_client) as client:
        session_name = f"cc-{chat_id}"
        stdout_file = f"/tmp/cc-{chat_id}.stdout"
        stderr_file = f"/tmp/cc-{chat_id}.stderr"
        exit_file = f"/tmp/cc-{chat_id}.exit"

        # 1. Stale cleanup
        _ssh_exec(
            client,
            f"tmux kill-session -t {_shell_quote(session_name)} 2>/dev/null; "
            f"rm -f /tmp/cc-{chat_id}.stdin /tmp/cc-{chat_id}.exit 2>/dev/null",
        )

        # 2. Per-backend setup (e.g. write SFTP stdin file for claude)
        if spec.setup:
            spec.setup(client, chat_id, prompt)

        # 3. Assemble tmux inner command
        inner_parts = ["date +%s > /tmp/ec2-ssh-last-seen;"]
        if env:
            for k, v in env.items():
                inner_parts.append(f"export {k}={_shell_quote(v)};")
        if cwd:
            inner_parts.append(f"cd {_shell_quote(cwd)} &&")

        exec_cmd = spec.build_exec(cmd, chat_id, prompt)
        inner_parts.append(
            f"{exec_cmd} "
            f"> {_shell_quote(stdout_file)} "
            f"2> {_shell_quote(stderr_file)}; "
            f"echo $? > {_shell_quote(exit_file)}"
        )

        tmux_cmd = (
            f"tmux new-session -d -s {_shell_quote(session_name)} "
            f"{_shell_quote(' '.join(inner_parts))}"
        )

        # 4. Start tmux session
        _ssh_exec(client, tmux_cmd)

        # 5. Sniff initial stdout for session/thread id
        await asyncio.sleep(2)

        initial_id: Optional[str] = None
        try:
            output = _ssh_exec(client, f"head -5 {_shell_quote(stdout_file)} 2>/dev/null")
            for line in output.strip().split("\n"):
                obj = parse_stream_line(line)
                if not obj:
                    continue
                initial_id = spec.parse_initial(obj)
                if initial_id:
                    break
        except Exception:
            pass

        return initial_id
