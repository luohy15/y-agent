"""Shared helpers for detached tmux-based execution over SSH.

The launch skeleton (SSH connect/teardown, stale cleanup, tmux wrap, and an
initial stdout sniff to extract a session id) lives here, parameterized by a
small `DetachBackendSpec` for the three hooks that are backend-specific (setup,
exec command assembly, initial id parsing). `start_detached_ssh` (claude_code) and `start_detached_codex_ssh` (codex)
are its callers. The spec seam is what keeps that launch path readable.

`tail_ssh_output` intentionally keeps its inline SSH bookkeeping; this module is
scoped to the start_* path.
"""

import asyncio
import json
import logging
import os
import time
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
from agent.tmp_guard import (
    DEFAULT_BUDGET_BYTES,
    DISK_FLOOR_BYTES,
    MIN_GROUP_AGE_SECONDS,
)


logger = logging.getLogger(__name__)

INITIAL_ID_WAIT_SECONDS = 2.0
INITIAL_ID_POLL_SECONDS = 0.1
ORPHAN_WRAPPER_MIN_AGE_SECONDS = 120
TMUX_SOCKET = "y-agent"


# Cleared before preflight on every launch, including a missing work dir.
# A previous run's stderr must not explain or classify this attempt.
# `model_catalog` is codex-only; the other backends simply never create it.
MODEL_CATALOG_SUFFIX = ".model-catalog.json"
ATTEMPT_LOG_SUFFIXES = (".stdin", ".stdout", ".stderr", ".exit", MODEL_CATALOG_SUFFIX)


def attempt_log_paths(chat_id: str) -> List[str]:
    return [f"/tmp/cc-{chat_id}{suffix}" for suffix in ATTEMPT_LOG_SUFFIXES]


def model_catalog_path(chat_id: str) -> str:
    return f"/tmp/cc-{chat_id}{MODEL_CATALOG_SUFFIX}"


def reset_attempt_logs_shell(chat_id: str) -> str:
    """Remove this attempt's stdout, stderr, stdin, exit and model-catalog files."""
    quoted = " ".join(_shell_quote(path) for path in attempt_log_paths(chat_id))
    return f"rm -f {quoted} 2>/dev/null || true"


def _tmux_command(args: str, legacy: bool = False, node=None) -> str:
    socket = "default" if legacy else TMUX_SOCKET
    binary = node.tmux_binary if node is not None else "tmux"
    return f"{binary} -L {socket} {args}"


def _tmux_alive_cmd(chat_id: str, node=None) -> str:
    # One-release transition: pre-deploy turns still live on the default socket.
    args = f"has-session -t {_shell_quote(f'=cc-{chat_id}')} 2>/dev/null"
    return f"( {_tmux_command(args, node=node)} || {_tmux_command(args, legacy=True, node=node)} )"


_TMUX_KILL_SCRIPT = """\
set +e
_t="$1"
_s="$2"
_pids=""
for _sock in y-agent default; do
  for _p in $("$_t" -L "$_sock" list-panes -t "=$_s" -F "#{pane_pid}" 2>/dev/null); do
    _pids="$_pids $_p"
  done
done
"$_t" -L y-agent kill-session -t "=$_s" 2>/dev/null
"$_t" -L default kill-session -t "=$_s" 2>/dev/null
_alive=""
for _p in $_pids; do
  case "$_p" in ""|*[!0-9]*|0|1) continue;; esac
  _alive="$_alive $_p"
  kill -TERM "-$_p" 2>/dev/null
done
_i=0
while [ "$_i" -lt 15 ] && [ -n "$_alive" ]; do
  _next=""
  for _p in $_alive; do
    kill -0 "-$_p" 2>/dev/null && _next="$_next $_p"
  done
  _alive="$_next"
  [ -n "$_alive" ] && sleep 0.2
  _i=$((_i + 1))
done
for _p in $_alive; do
  kill -KILL "-$_p" 2>/dev/null
done
_i=0
while [ "$_i" -lt 5 ] && [ -n "$_alive" ]; do
  _next=""
  for _p in $_alive; do
    kill -0 "-$_p" 2>/dev/null && _next="$_next $_p"
  done
  _alive="$_next"
  [ -n "$_alive" ] && sleep 0.2
  _i=$((_i + 1))
done
[ -z "$_alive" ] || exit 1
( "$_t" -L y-agent has-session -t "=$_s" 2>/dev/null || "$_t" -L default has-session -t "=$_s" 2>/dev/null ) && exit 1
exit 0
"""


def _tmux_kill_cmd(chat_id: str, node=None) -> str:
    """Kill the session and every process group its panes started.

    `tmux kill-session` only sends SIGHUP to the pane, so a backend that ignores
    SIGHUP (Antigravity's `agy`) survives as a PPID=1 orphan while the next turn
    launches a second process on the same conversation (todo 4472). Capture each
    pane's PID (its session and process-group leader) on both sockets, kill the
    session, then TERM the captured groups and escalate to KILL. Guard `0`/`1`/
    non-numeric panes so a bad PID cannot signal the caller's own group or init.
    Exit 0 only when the session and every captured group are gone.

    POSIX `sh -c` so the same script runs under zsh / bash / sh on Linux and macOS.
    """
    binary = node.tmux_binary if node is not None else "tmux"
    return (
        f"sh -c {_shell_quote(_TMUX_KILL_SCRIPT)} sh "
        f"{_shell_quote(binary)} {_shell_quote(f'cc-{chat_id}')}"
    )


def _reap_orphan_wrappers_cmd(min_age_s: float = ORPHAN_WRAPPER_MIN_AGE_SECONDS, stdin_prefix: str = "/tmp/cc-") -> str:
    """Remote command that reaps leaked session wrappers (see `agent.orphan_reaper`)."""
    from agent import orphan_reaper

    source = Path(orphan_reaper.__file__).read_text()
    return f"python3 -c {_shell_quote(source)} {_shell_quote(str(min_age_s))} {_shell_quote(stdin_prefix)}"


class InsufficientDiskSpace(RuntimeError):
    """A measured run-dir shortfall the launch refused to start on.

    Raised through the launch error path when the run dir is too full to hold
    the refusal record itself; its text is the whole diagnostic.
    """


class StagingLockUnavailable(RuntimeError):
    """The per-chat staging lock could not be confirmed; nothing was staged."""

    def __init__(self, chat_id: str, cause: str):
        self.chat_id = chat_id
        self.cause = cause
        super().__init__(
            f"staging lock unavailable for chat {chat_id} ({cause}); "
            f"nothing was uploaded, staged, or started."
        )


def _gc_attempts_cmd(run_dir: str, floor_bytes: int, tmux_binary: str = "tmux") -> str:
    """Remote command that bounds harness-owned attempt data, then reports free space.

    One call does both so the launch preflight stays one SSH round trip: the
    sweep runs first, then the floor is measured against the reclaimed room.
    """
    from agent import tmp_guard

    source = Path(tmp_guard.__file__).read_text()
    argv = [
        "gc",
        "--run-dir", run_dir,
        "--budget", str(DEFAULT_BUDGET_BYTES),
        "--min-age", str(MIN_GROUP_AGE_SECONDS),
        "--tmux", tmux_binary,
        "--floor", str(floor_bytes),
    ]
    return f"python3 -c {_shell_quote(source)} " + " ".join(_shell_quote(part) for part in argv)


def _free_bytes_line(line: str) -> Optional[int]:
    """Parse the `free=<bytes>` field out of a `tmp_guard` free line."""
    for part in line.split():
        if part.startswith("free="):
            try:
                return int(part[len("free="):])
            except ValueError:
                return None
    return None


# Holds a per-chat advisory lock until stdin closes. Shares the lock file with
# `tmp_guard` (GC / terminal cleanup) and the orphan reaper, so launch staging
# and every destructive check-and-delete are mutually exclusive.
_CHAT_LOCK_HELPER = (
    "import fcntl,sys;"
    "f=open(sys.argv[1],'a');"
    "fcntl.flock(f, fcntl.LOCK_EX);"
    "sys.stdout.write('locked\\n');"
    "sys.stdout.flush();"
    "sys.stdin.read()"
)


@contextmanager
def _chat_lock(client, chat_id: str, run_dir: str):
    """Hold the per-chat staging lock for the duration of the block.

    Every artifact a launch creates (stdin, images, codex home, MCP dirs) is
    written inside this block, so a destructive path's check-and-unlink cannot
    interleave with a replacement generation (todo 4487 review round 2). The
    block is only entered with confirmed ownership: a timeout, a missing
    `locked` line or a helper error raises `StagingLockUnavailable` before
    anything is staged. There is no unlocked staging path.
    """
    lock = f"{run_dir}/.cc-{chat_id}.lock"
    cmd = f"python3 -c {_shell_quote(_CHAT_LOCK_HELPER)} {_shell_quote(lock)}"
    stdin = stdout = None
    try:
        stdin, stdout, _stderr = client.exec_command(cmd, timeout=30)
        if stdout.readline().strip() != "locked":
            raise RuntimeError("lock helper did not confirm")
    except Exception as exc:
        if stdout is not None:
            try:
                stdout.channel.close()
            except Exception:
                pass
        raise StagingLockUnavailable(chat_id, f"{type(exc).__name__}: {exc}") from exc
    try:
        yield
    finally:
        try:
            stdin.close()
        except Exception:
            pass
        try:
            stdout.channel.recv_exit_status()
        except Exception:
            pass


async def _await_attempt_stdout(client, stdout_file: str, wait_seconds: float):
    """Wait until the wrapper has created its stdout redirect.

    The launch keeps the chat lock until the wrapper's first redirect exists,
    so that creation cannot interleave with a destructive check-and-delete. A
    timeout is not fatal: the initial-id sniff still reports what it sees.
    """
    probe = f"test -f {_shell_quote(stdout_file)} && echo ok || echo no"
    deadline = time.monotonic() + min(max(wait_seconds, 0.5), 5.0)
    while True:
        try:
            if _ssh_exec(client, probe).strip() == "ok":
                return
        except Exception:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(0.05, remaining))


def attempt_artifact_cleanup_cmd(chat_id: str, before: Optional[float] = None,
                                 run_dir: str = "/tmp") -> str:
    """Remove per-chat staging a finished turn no longer needs.

    `before` is the instant the turn reached a terminal state. The remote
    helper removes only entries older than it, so a new turn that stages the
    same chat during closeout keeps its own generation. The tmux wrapper's EXIT
    trap removes a backend's own staging, but a killed wrapper, a hard timeout,
    or a full run dir can leave images, a codex home or MCP staging behind until
    the same chat happens to launch again.
    """
    from agent import tmp_guard

    source = Path(tmp_guard.__file__).read_text()
    stamp = time.time() if before is None else before
    argv = [
        "clean",
        "--run-dir", run_dir,
        "--chat", chat_id,
        "--before", f"{float(stamp):.3f}",
    ]
    return f"python3 -c {_shell_quote(source)} " + " ".join(_shell_quote(part) for part in argv)


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
    - `after_initial(client, chat_id, prompt, images, initial_id)` — optional,
      runs once after the initial-id sniff. Codex app-server is a two-phase
      launch: the thread id must be known before `turn/start` can be appended
      to the stdin pipe.
    - `initial_stdout_lines` / `initial_wait_seconds` — how much of the stdout
      file the sniff reads and how long it waits. App-server startup warnings
      can push the thread id past the default five lines.
    """

    build_exec: Callable[[List[str], str, str, Optional[List[str]]], str]
    parse_initial: Callable[[Dict], Optional[str]]
    setup: Optional[Callable[[object, str, str, Optional[List[str]]], None]] = None
    after_initial: Optional[
        Callable[[object, str, str, Optional[List[str]], Optional[str]], None]
    ] = None
    upload_images: bool = True
    cleanup: Optional[Callable[[], str]] = None
    # Wrapper EXIT command. Defaults to `cleanup`; app-server passes a no-op so
    # the staged home survives a process crash until the tail has copied the
    # rollout back (the tail removes it after syncing).
    trap_cleanup: Optional[Callable[[], str]] = None
    initial_stdout_lines: int = 5
    initial_wait_seconds: float = INITIAL_ID_WAIT_SECONDS
    # Free bytes the launch requires under the node's run dir after the GC.
    # A backend that stages its own runtime raises it (codex app-server).
    free_space_floor_bytes: int = DISK_FLOOR_BYTES


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


def upload_steer_images(client, chat_id: str, msg_id: str,
                        images: Optional[List[str]]) -> List[str]:
    """Stage a steer's images on the node under a per-message subdirectory.

    The launch uploads to `/tmp/cc-<chat_id>-images/<index>-<name>`; a steer
    uses `/tmp/cc-<chat_id>-images/<msg_id>/<index>-<name>` so filenames cannot
    collide. The next launch removes the whole image directory.
    """
    if not images:
        return []

    remote_dir = f"/tmp/cc-{chat_id}-images/{msg_id}"
    _ssh_exec(client, f"mkdir -p {_shell_quote(remote_dir)}")
    sftp = client.open_sftp()
    staged_files: List[Path] = []
    try:
        remote_paths = []
        for index, image_path in enumerate(images):
            source = (_download_s3_to_tmp(image_path, chat_id)
                      if _is_s3_uri(image_path) else Path(image_path).expanduser())
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
      0. Acquire the per-chat staging lock. An unconfirmed acquisition aborts
         the launch before anything on the node is killed, removed or written.
      1. Kill any stale `cc-<chat_id>` tmux session and remove this attempt's
         stdin/stdout/stderr/exit files, plus any leftover `.killed` sentinel
         from a prior turn's steer/interrupt teardown (see
         `_kill_session_marking_self_killed` in claude_code.py) so it can't
         mask a genuine death in this new turn.
      2. Run backend-specific `spec.setup` (optional).
      3. Build the tmux inner command: last-seen touch, env exports,
         optional `cd`, backend exec (from `spec.build_exec`), stdout/stderr
         redirect, and exit-code capture.
      4. Launch `tmux new-session -d -s cc-<chat_id> <inner>`.
      5. Poll the first few stdout lines for up to 2s. Return the id from
         `spec.parse_initial` as soon as it parses, else None.
    """
    with _with_ssh_client(node, ssh_client) as client:
        session_name = f"cc-{chat_id}"
        stdout_file = f"/tmp/cc-{chat_id}.stdout"
        stderr_file = f"/tmp/cc-{chat_id}.stderr"
        exit_file = f"/tmp/cc-{chat_id}.exit"

        # Everything that touches this chat's shared paths runs only after the
        # lock is confirmed: the host-wide reaper, the stale-session teardown,
        # the log reset, the staging, the tmux start, and the floor refusal
        # record. A competing launch that cannot take the lock must leave the
        # holder's files and session untouched (todo 4487 review round 4).
        with _chat_lock(client, chat_id, node.tmp_dir):
            # Host-wide guard: wrappers whose tmux session is gone but whose
            # process tree survived (todo 3819). Never fails the launch. It
            # takes each chat's own lock before removing that chat's staged
            # home, so it never touches a launch that holds the lock.
            # The reaper reads /proc, so it does not run on macOS.
            if node.reaper:
                try:
                    reaped = _ssh_exec(client, _reap_orphan_wrappers_cmd()).strip()
                    if reaped and reaped != "reaped=0":
                        logger.warning("reaped orphaned session wrappers on launch of %s: %s", session_name, reaped)
                except Exception as exc:
                    logger.warning("orphaned session wrapper reap failed on launch of %s: %s", session_name, exc)

            # 1. Stale session cleanup, then drop this attempt's log files
            # before any preflight (including the missing-cwd path below) so a
            # previous run's stderr cannot be read as this failure.
            from agent.mcp.staging import cleanup_command
            _ssh_exec(
                client,
                f"{_tmux_kill_cmd(chat_id, node=node)}; "
                f"{reset_attempt_logs_shell(chat_id)}; "
                f"rm -f /tmp/cc-{chat_id}.killed /tmp/cc-{chat_id}.claude-ec 2>/dev/null; "
                f"rm -rf /tmp/cc-{chat_id}-images 2>/dev/null; "
                + cleanup_command(chat_id),
            )

            # Bound the host's harness-owned attempt data, then refuse to
            # stage a turn that has no room for its own logs (todo 4487). A
            # sweep error never blocks a launch; a measured shortfall does,
            # because the turn would otherwise die part-way with a misleading
            # error.
            free_bytes = None
            try:
                out = _ssh_exec(
                    client,
                    _gc_attempts_cmd(node.tmp_dir, spec.free_space_floor_bytes, node.tmux_binary),
                )
                for line in out.splitlines():
                    if line.startswith("gc "):
                        logger.info("run-dir gc on launch of %s: %s", session_name, line)
                    elif line.startswith("free="):
                        free_bytes = _free_bytes_line(line)
            except Exception as exc:
                logger.warning("run-dir gc/floor check failed on launch of %s: %s", session_name, exc)
            if free_bytes is not None and free_bytes < spec.free_space_floor_bytes:
                message = (
                    f"insufficient free space under {node.tmp_dir} on the execution node: "
                    f"{free_bytes // (1024 * 1024)} MB free, below the "
                    f"{spec.free_space_floor_bytes // (1024 * 1024)} MB launch floor. "
                    f"Nothing was started; free space on the node and retry."
                )
                error_obj = (
                    {"type": "result", "is_error": True, "result": message}
                    if spec.setup
                    else {"type": "error", "message": message}
                )
                # The refusal must survive an exhausted filesystem: try the
                # usual terminal record, but if that write fails too, carry the
                # measured refusal through the launch error path instead of
                # losing it.
                recorded = False
                try:
                    _ssh_exec(
                        client,
                        f"printf '%s\\n' {_shell_quote(json.dumps(error_obj))} > {_shell_quote(stdout_file)} && "
                        f"echo 1 > {_shell_quote(exit_file)}",
                    )
                    recorded = True
                except Exception as exc:
                    logger.warning("disk-floor refusal record unwritable on launch of %s: %s", session_name, exc)
                if not recorded:
                    raise InsufficientDiskSpace(message)
                return None

            # 2-4. Staging, setup, and the tmux start continue under the lock.
            # Every destructive path (terminal cleanup, GC, reaper) takes the
            # same lock, so no replacement generation can be created between
            # such a path's check and its unlink. The lock is held until the
            # wrapper's own redirect files exist.
            staged, exec_images = _stage_turn(
                client, node, spec, chat_id, cmd, prompt, cwd, env, images, unset_env,
                stdout_file, stderr_file, exit_file, session_name,
            )
            if not staged:
                return None
            await _await_attempt_stdout(client, stdout_file, spec.initial_wait_seconds)

        # 5. Sniff initial stdout for session/thread id. The budget matches
        # the previous fixed sleep; a ready id returns on the first read.
        stdout_read = (
            f"head -{int(spec.initial_stdout_lines)} {_shell_quote(stdout_file)} 2>/dev/null"
        )
        initial_id = await _await_initial_id(
            lambda: _ssh_exec(client, stdout_read),
            spec.parse_initial,
            spec.initial_wait_seconds,
        )
        # 6. Backend follow-up that needs the id (app-server `turn/start`).
        if spec.after_initial:
            try:
                spec.after_initial(client, chat_id, prompt, exec_images, initial_id)
            except Exception:
                # The session was already started in step 4. A failed follow-up
                # must kill it (and its stdin pipe), then run the backend
                # cleanup, so no unreported process is left behind.
                try:
                    _ssh_exec(client, _tmux_kill_cmd(chat_id, node=node))
                except Exception:
                    pass
                if spec.cleanup:
                    _ssh_exec(client, spec.cleanup())
                raise
        return initial_id


def _stage_turn(client, node, spec: DetachBackendSpec, chat_id: str, cmd, prompt: str,
                cwd: Optional[str], env, images, unset_env, stdout_file: str,
                stderr_file: str, exit_file: str, session_name: str):
    """Upload images, run setup, and start the tmux session.

    Runs inside the per-chat staging lock. Returns `(ok, exec_images)`; `ok` is
    False when the missing-work-dir record was written instead of a launch.
    """
    exec_images = _upload_images(client, chat_id, images) if spec.upload_images else images

    # Per-backend setup (e.g. write SFTP stdin file for claude)
    if spec.setup:
        try:
            spec.setup(client, chat_id, prompt, exec_images)
        except Exception:
            if spec.cleanup:
                _ssh_exec(client, spec.cleanup())
            raise

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
            return False, exec_images

    # Assemble tmux inner command
    exec_cmd = spec.build_exec(cmd, chat_id, prompt, exec_images)
    inner = assemble_inner(
        env=env,
        cwd=cwd,
        exec_cmd=exec_cmd,
        heartbeat=node.heartbeat,
        stdout_file=stdout_file,
        stderr_file=stderr_file,
        exit_file=exit_file,
        # Wrapper EXIT trap: `trap_cleanup` when the backend sets one (codex
        # app-server keeps its staged home until the tail syncs, todo 4476),
        # otherwise the backend's own cleanup.
        cleanup=(spec.trap_cleanup() if spec.trap_cleanup is not None
                 else (spec.cleanup() if spec.cleanup else None)),
        unset_env=unset_env,
    )

    tmux_cmd = (
        f"{_tmux_command('new-session', node=node)} -d -s {_shell_quote(session_name)} "
        f"{_shell_quote(inner)}"
    )

    # Start tmux session. A zero exit here means tmux accepted the session
    # command. It does not mean the wrapped process is healthy.
    try:
        _ssh_exec(client, tmux_cmd)
    except Exception:
        if spec.cleanup:
            _ssh_exec(client, spec.cleanup())
        raise
    return True, exec_images


async def _await_initial_id(
    read_output, parse_initial, wait_seconds: float = INITIAL_ID_WAIT_SECONDS,
) -> Optional[str]:
    """Return the first parsed id, or None when the budget is spent.

    The first read is immediate. Later reads are about 100ms apart, and one
    read still happens at the deadline. A read or parse error is ignored for
    that attempt and does not raise or end the wait early.
    """
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            output = read_output()
            for line in output.strip().split("\n"):
                obj = parse_stream_line(line)
                if not obj:
                    continue
                initial_id = parse_initial(obj)
                if initial_id:
                    return initial_id
        except Exception:
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        await asyncio.sleep(min(INITIAL_ID_POLL_SECONDS, remaining))
