"""Shared helpers for detached tmux-based execution over SSH.

The launch skeleton (SSH connect/teardown, stale cleanup, tmux wrap, and an
initial stdout sniff to extract a session id) lives here, parameterized by a
small `DetachBackendSpec` for the three hooks that are backend-specific (setup,
exec command assembly, initial id parsing). `start_detached_ssh` (claude_code)
is its only caller since the other agentic CLI backends were removed (todo
2930); the spec seam is kept because it is what keeps that launch path
readable.

`tail_ssh_output` intentionally keeps its inline SSH bookkeeping; this module is
scoped to the start_* path.
"""

import asyncio
import json
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from typing import Callable, Dict, List, Optional

from agent.claude_code import (
    _shell_quote,
    _ssh_exec,
    parse_stream_line,
)


logger = logging.getLogger(__name__)

ORPHAN_WRAPPER_MIN_AGE_SECONDS = 120
TMUX_SOCKET = "y-agent"


def _tmux_command(args: str, legacy: bool = False, node=None) -> str:
    socket = "default" if legacy else TMUX_SOCKET
    binary = node.tmux_binary if node is not None else "tmux"
    return f"{binary} -L {socket} {args}"


def _tmux_alive_cmd(chat_id: str, node=None) -> str:
    # One-release transition: pre-deploy turns still live on the default socket.
    args = f"has-session -t {_shell_quote(f'=cc-{chat_id}')} 2>/dev/null"
    return f"( {_tmux_command(args, node=node)} || {_tmux_command(args, legacy=True, node=node)} )"


def _tmux_kill_cmd(chat_id: str, node=None) -> str:
    args = f"kill-session -t {_shell_quote(f'=cc-{chat_id}')} 2>/dev/null"
    return f"( {_tmux_command(args, node=node)}; {_tmux_command(args, legacy=True, node=node)} )"


def _reap_orphan_wrappers_cmd(min_age_s: float = ORPHAN_WRAPPER_MIN_AGE_SECONDS, stdin_prefix: str = "/tmp/cc-") -> str:
    """Remote command that reaps leaked session wrappers (see `agent.orphan_reaper`)."""
    from agent import orphan_reaper

    source = Path(orphan_reaper.__file__).read_text()
    return f"python3 -c {_shell_quote(source)} {_shell_quote(str(min_age_s))} {_shell_quote(stdin_prefix)}"


@contextmanager
def _with_ssh_client(node, ssh_client=None):
    """Yield a paramiko SSHClient for `node`, connecting if not passed.

    If the caller supplies `ssh_client` (from a pool), it is reused and left
    open. Otherwise a fresh connection is opened and closed on exit. Jump nodes
    keep the anchor session only as the direct-tcpip outer hop.
    """
    owns_client = ssh_client is None
    if owns_client:
        from agent.chat_target import open_owned_client

        ssh_client = open_owned_client(node)

    try:
        yield ssh_client
    finally:
        if owns_client:
            from agent.chat_target import close_owned_client

            close_owned_client(ssh_client)


@dataclass
class DetachBackendSpec:
    """Per-backend hooks for `_start_detached_tmux`.

    - `setup(client, chat_id, prompt, images)` — optional, runs after stale cleanup
      and before the tmux command is assembled (e.g. write a stream-json
      stdin file via SFTP).
    - `build_exec(cmd, chat_id, prompt, images) -> str` — the exec command string that
      goes between the `cd` clause and the stdout/stderr redirect.
    - `parse_initial(obj) -> Optional[str]` — inspect a parsed stream-json
      event from the first few stdout lines and return the session/thread id
      if this event carries it; return None to keep scanning.
    """

    build_exec: Callable[[List[str], str, str, Optional[List[str]]], str]
    parse_initial: Callable[[Dict], Optional[str]]
    setup: Optional[Callable[[object, str, str, Optional[List[str]]], None]] = None
    upload_images: bool = True
    cleanup: Optional[Callable[[], str]] = None
    launch_env: Optional[Callable[[], Dict[str, str]]] = None


def _upload_images(client, chat_id: str, images: Optional[List[str]]) -> Optional[List[str]]:
    if not images:
        return None
    remote_dir = f"/tmp/cc-{chat_id}-images"
    _ssh_exec(client, f"mkdir -p {_shell_quote(remote_dir)}")
    sftp = client.open_sftp()
    staged_files: List[Path] = []
    try:
        remote_paths = []
        for index, image_path in enumerate(images):
            source = _download_s3_to_tmp(image_path, chat_id) if _is_s3_uri(image_path) else Path(image_path).expanduser()
            if _is_s3_uri(image_path):
                staged_files.append(source)
            if not source.exists():
                remote_paths.append(image_path)
                continue
            remote_path = f"{remote_dir}/{index}-{source.name}"
            sftp.put(str(source), remote_path)
            remote_paths.append(remote_path)
        return remote_paths
    finally:
        sftp.close()
        for staged_file in staged_files:
            try:
                staged_file.unlink()
            except FileNotFoundError:
                pass


def _is_s3_uri(uri: str) -> bool:
    return isinstance(uri, str) and uri.startswith("s3://")


def assemble_inner(
    *,
    env,
    cwd,
    exec_cmd: str,
    heartbeat: bool,
    stdout_file: str,
    stderr_file: str,
    exit_file: str,
    cleanup: Optional[str] = None,
    unset_env: Optional[List[str]] = None,
) -> str:
    """Shell body tmux runs. EC2 keeps the last-seen heartbeat; mac does not.

    ``unset_env`` is emitted before any export so a stale tmux environment
    cannot keep relay credentials that this launch intentionally dropped.
    """
    inner_parts = ["unset TMUX;"]
    if unset_env:
        inner_parts.append("unset " + " ".join(unset_env) + ";")
    if heartbeat:
        inner_parts.extend([
            "date +%s > /tmp/ec2-ssh-last-seen;",
            "( while :; do date +%s > /tmp/ec2-ssh-last-seen; sleep 60; done ) &",
            "HEARTBEAT_PID=$!;",
        ])
    if cleanup:
        inner_parts.append(f"trap {_shell_quote(cleanup)} EXIT;")
    if env:
        for key, value in env.items():
            inner_parts.append(f"export {key}={_shell_quote(value)};")
    if cwd:
        inner_parts.append(f"cd {_shell_quote(cwd)} &&")
    finish = (
        f"{exec_cmd} "
        f"> {_shell_quote(stdout_file)} "
        f"2> {_shell_quote(stderr_file)}; "
        "EC=$?; "
    )
    if heartbeat:
        finish += "kill $HEARTBEAT_PID 2>/dev/null; "
    finish += f"echo $EC > {_shell_quote(exit_file)}"
    inner_parts.append(finish)
    return " ".join(inner_parts)


def build_launch_plan(node, chat_id: str, cmd, env=None, cwd=None, prompt: str = "",
                      unset_env=None) -> dict:
    """Launch text for one node, with no SSH. Used by the mac command check."""
    from agent.chat_target import apply_launch
    from agent.claude_code import _claude_build_exec

    argv, exported = apply_launch(node, cmd, env)
    inner = assemble_inner(
        env=exported,
        cwd=cwd,
        exec_cmd=_claude_build_exec(argv, chat_id, prompt, None),
        heartbeat=node.heartbeat,
        stdout_file=f"/tmp/cc-{chat_id}.stdout",
        stderr_file=f"/tmp/cc-{chat_id}.stderr",
        exit_file=f"/tmp/cc-{chat_id}.exit",
        unset_env=unset_env,
    )
    return {
        "inner": inner,
        "reaper_command": _reap_orphan_wrappers_cmd() if node.reaper else None,
        "tmux_command": _tmux_command("new-session", node=node),
    }


def _download_s3_to_tmp(uri: str, chat_id: str = "image") -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError(f"invalid s3 image uri: {uri}")

    key = parsed.path.lstrip("/")
    filename = Path(key).name or "image"
    tmp_dir = Path(os.environ.get("Y_AGENT_IMAGE_TMP_DIR", "/tmp")) / f"cc-{chat_id}-images"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / filename

    import boto3

    boto3.client("s3").download_file(parsed.netloc, key, str(target))
    return target


async def _start_detached_tmux(
    cmd: List[str],
    prompt: str,
    cwd: Optional[str],
    chat_id: str,
    node,
    spec: DetachBackendSpec,
    env: Optional[Dict[str, str]] = None,
    images: Optional[List[str]] = None,
    ssh_client=None,
    unset_env: Optional[List[str]] = None,
) -> Optional[str]:
    """Shared skeleton for starting a detached tmux session over SSH.

    Steps:
      1. Kill any stale `cc-<chat_id>` tmux session and remove leftover
         stdin/exit files, plus any leftover `.killed` self-kill sentinel
         from a prior turn's steer/interrupt teardown (see
         `_kill_session_marking_self_killed` in claude_code.py) so it can't
         mask a genuine death in this new turn.
      2. Run backend-specific `spec.setup` (optional).
      3. Build the tmux inner command: last-seen touch, env exports,
         optional `cd`, backend exec (from `spec.build_exec`), stdout/stderr
         redirect, and exit-code capture.
      4. Launch `tmux new-session -d -s cc-<chat_id> <inner>`.
      5. Sleep briefly, read the first few stdout lines, and extract the
         initial id via `spec.parse_initial`.
    """
    with _with_ssh_client(node, ssh_client) as client:
        session_name = f"cc-{chat_id}"
        stdout_file = f"/tmp/cc-{chat_id}.stdout"
        stderr_file = f"/tmp/cc-{chat_id}.stderr"
        exit_file = f"/tmp/cc-{chat_id}.exit"

        # 1. Stale cleanup
        from agent.mcp.staging import cleanup_command
        from agent.skills_share import cleanup_command as skill_cleanup_command
        _ssh_exec(
            client,
            f"{_tmux_kill_cmd(chat_id, node=node)}; "
            f"rm -f /tmp/cc-{chat_id}.stdin /tmp/cc-{chat_id}.exit /tmp/cc-{chat_id}.killed /tmp/cc-{chat_id}.claude-ec 2>/dev/null; "
            f"rm -rf /tmp/cc-{chat_id}-images 2>/dev/null; "
            + cleanup_command(chat_id) + '; ' + skill_cleanup_command(chat_id),
        )
        # Host-wide guard: wrappers whose tmux session is gone but whose
        # process tree survived (todo 3819). Never fails the launch.
        # The reaper reads /proc, so it does not run on macOS.
        if node.reaper:
            try:
                reaped = _ssh_exec(client, _reap_orphan_wrappers_cmd()).strip()
                if reaped and reaped != "reaped=0":
                    logger.warning("reaped orphaned session wrappers on launch of %s: %s", session_name, reaped)
            except Exception as exc:
                logger.warning("orphaned session wrapper reap failed on launch of %s: %s", session_name, exc)

        exec_images = _upload_images(client, chat_id, images) if spec.upload_images else images

        # 2. Per-backend setup (e.g. write SFTP stdin file for claude)
        if spec.setup:
            try:
                spec.setup(client, chat_id, prompt, exec_images)
            except Exception:
                if spec.cleanup:
                    _ssh_exec(client, spec.cleanup())
                raise
        if spec.launch_env:
            env = {**(env or {}), **spec.launch_env()}

        if cwd:
            cwd_exists = _ssh_exec(client, f"test -d {_shell_quote(cwd)} && echo ok || echo missing").strip() == "ok"
            if not cwd_exists:
                message = f"work_dir not found: {cwd}"
                error_obj = (
                    {"type": "result", "is_error": True, "result": message}
                    if spec.setup
                    else {"type": "error", "message": message}
                )
                _ssh_exec(
                    client,
                    f"printf '%s\\n' {_shell_quote(json.dumps(error_obj))} > {_shell_quote(stdout_file)}; "
                    f"echo 1 > {_shell_quote(exit_file)}",
                )
                if spec.cleanup:
                    _ssh_exec(client, spec.cleanup())
                return None

        # 3. Assemble tmux inner command
        exec_cmd = spec.build_exec(cmd, chat_id, prompt, exec_images)
        inner = assemble_inner(
            env=env,
            cwd=cwd,
            exec_cmd=exec_cmd,
            heartbeat=node.heartbeat,
            stdout_file=stdout_file,
            stderr_file=stderr_file,
            exit_file=exit_file,
            cleanup=spec.cleanup() if spec.cleanup else None,
            unset_env=unset_env,
        )

        tmux_cmd = (
            f"{_tmux_command('new-session', node=node)} -d -s {_shell_quote(session_name)} "
            f"{_shell_quote(inner)}"
        )

        # 4. Start tmux session. A zero exit here means tmux accepted the
        # session command. It does not mean the wrapped process is healthy.
        try:
            _ssh_exec(client, tmux_cmd)
        except Exception:
            if spec.cleanup:
                _ssh_exec(client, spec.cleanup())
            raise

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
