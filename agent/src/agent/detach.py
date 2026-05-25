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
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from typing import Callable, Dict, List, Optional

from agent.claude_code import (
    _parse_ssh_target,
    _shell_quote,
    _ssh_exec,
    parse_stream_line,
)
from agent.ec2_wake import ensure_and_touch_vm


SSH_CONNECT_TIMEOUT_SECONDS = 30


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

        ensure_and_touch_vm(vm_config)

        user, host, port = _parse_ssh_target(vm_config.vm_name)
        key = paramiko.Ed25519Key.from_private_key(io.StringIO(vm_config.api_token))

        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(
            host,
            port=port,
            username=user,
            pkey=key,
            timeout=SSH_CONNECT_TIMEOUT_SECONDS,
        )

    try:
        yield ssh_client
    finally:
        if owns_client:
            ssh_client.close()


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
    vm_config,
    spec: DetachBackendSpec,
    env: Optional[Dict[str, str]] = None,
    images: Optional[List[str]] = None,
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
            f"rm -f /tmp/cc-{chat_id}.stdin /tmp/cc-{chat_id}.exit 2>/dev/null; "
            f"rm -rf /tmp/cc-{chat_id}-images 2>/dev/null",
        )

        exec_images = _upload_images(client, chat_id, images) if spec.upload_images else images

        # 2. Per-backend setup (e.g. write SFTP stdin file for claude)
        if spec.setup:
            spec.setup(client, chat_id, prompt, exec_images)

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
                return None

        # 3. Assemble tmux inner command
        inner_parts = [
            "date +%s > /tmp/ec2-ssh-last-seen;",
            "( while :; do date +%s > /tmp/ec2-ssh-last-seen; sleep 60; done ) &",
            "HEARTBEAT_PID=$!;",
        ]
        if env:
            for k, v in env.items():
                inner_parts.append(f"export {k}={_shell_quote(v)};")
        if cwd:
            inner_parts.append(f"cd {_shell_quote(cwd)} &&")

        exec_cmd = spec.build_exec(cmd, chat_id, prompt, exec_images)
        inner_parts.append(
            f"{exec_cmd} "
            f"> {_shell_quote(stdout_file)} "
            f"2> {_shell_quote(stderr_file)}; "
            "EC=$?; "
            "kill $HEARTBEAT_PID 2>/dev/null; "
            f"echo $EC > {_shell_quote(exit_file)}"
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
