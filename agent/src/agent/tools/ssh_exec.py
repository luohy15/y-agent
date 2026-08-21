import asyncio
import functools
import io
from concurrent.futures import ThreadPoolExecutor

import paramiko
from loguru import logger

from storage.entity.dto import VmConfig
from agent.ec2_wake import ensure_and_touch_vm
from agent.tools.errors import CommandError


# Paramiko is blocking, so both halves of an ssh_exec (the EC2/DB prelude and
# the command itself) run in a thread. Not the loop's default executor:
# `asyncio.run()`'s teardown awaits `loop.shutdown_default_executor()`, so an
# abandoned default-executor thread adds its remaining runtime back onto the
# caller — which for `worker/handler.py`'s scheduled actions is the Lambda
# invocation itself (todo 3226). And not shared with the usage-limit sweep's
# bookkeeping executor either: a stuck SSH session must not be able to delay
# that sweep's own DB work, nor the reverse.
#
# A thread here cannot be cancelled, so the bound comes from the work: the
# prelude's EC2 calls carry botocore timeouts inside agent.ec2_wake (a cold
# wake is deliberately still allowed to take as long as a cold boot takes),
# and the command below carries socket timeouts plus the force-close that
# unblocks a stuck read. `_MAX_WORKERS` therefore sizes
# ordinary concurrency (tool calls, terminal, vm_command, and the usage
# sweep's own ceiling of eight CLI reads), not a safety margin for stuck
# threads: if a lingering wake does occupy a worker, later calls queue until
# their own caller's timeout fires and are retried on the next pass, rather
# than the pool growing to hide it.
_MAX_WORKERS = 8

_EXECUTOR = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="ssh-exec")


async def _offload(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_EXECUTOR, functools.partial(func, *args, **kwargs))


def _parse_ssh_target(vm_name: str) -> tuple:
    """Parse 'ssh:user@host:port' or 'ssh:host' into (user, host, port)."""
    raw = vm_name[len("ssh:"):]
    user = None
    port = 22
    if "@" in raw:
        user, raw = raw.split("@", 1)
    if ":" in raw:
        host, port_str = raw.rsplit(":", 1)
        port = int(port_str)
    else:
        host = raw
    return user, host, port


def _shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


async def ssh_exec(vm_config: VmConfig, cmd: list[str], stdin: str | None = None, dir: str | None = None, timeout: float = 30, check: bool = False) -> str:
    # Off the loop: this prelude can do a boto3 describe/start, an SSH-ready
    # poll, and a DB write, and running it inline blocked the caller's event
    # loop — which defeats any timeout the caller wrapped around this call
    # (todo 3226: the usage-limit sweep bounds each user that way). Its own
    # wall clock is bounded in agent.ec2_wake, not here: a cancelled caller
    # abandons this thread and only the operation itself can end it.
    await _offload(ensure_and_touch_vm, vm_config)
    user, host, port = _parse_ssh_target(vm_config.vm_name)
    key = paramiko.Ed25519Key.from_private_key(io.StringIO(vm_config.api_token))

    parts = ["date +%s > /tmp/ec2-ssh-last-seen;"]
    if dir:
        parts.append(f"cd {_shell_quote(dir)} &&")
    parts.append(" ".join(_shell_quote(c) for c in cmd))
    shell_cmd = " ".join(parts)

    logger.info("ssh_exec host={} port={} user={} cmd={}", host, port, user, shell_cmd)

    # asyncio.wait_for cannot cancel a thread running in the executor: on
    # timeout the thread below keeps blocking on stdout_ch.read(). Stash the
    # client here as soon as it exists so the timeout handler can force-close
    # it from the event loop thread, which unblocks the read (and therefore
    # the executor thread) instead of leaking the connection indefinitely.
    # The same close runs when the *caller* is cancelled (the usage-limit
    # sweep cancels an attempt that outlives its per-user cap), so an
    # abandoned command frees its worker and its socket immediately instead
    # of running on to its own socket timeouts.
    client_holder: dict[str, paramiko.SSHClient] = {}

    def _run():
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client_holder["client"] = client
        # banner_timeout/auth_timeout as well as the connect timeout: a host
        # that completes the TCP handshake and then goes quiet would otherwise
        # hold this thread for paramiko's 15s/30s defaults on top of `timeout`.
        client.connect(
            host, port=port, username=user, pkey=key,
            timeout=timeout, banner_timeout=timeout, auth_timeout=timeout,
        )

        stdin_ch, stdout_ch, stderr_ch = client.exec_command(shell_cmd, timeout=timeout)
        if stdin:
            stdin_ch.write(stdin)
        stdin_ch.close()

        result = stdout_ch.read().decode("utf-8", errors="replace")
        exit_status = stdout_ch.channel.recv_exit_status()
        client.close()

        logger.info("ssh_exec done exit_status={} stdout_len={}", exit_status, len(result))
        return result, exit_status

    loop = asyncio.get_running_loop()
    try:
        result, exit_status = await asyncio.wait_for(
            loop.run_in_executor(_EXECUTOR, _run), timeout=timeout
        )
    except (asyncio.TimeoutError, asyncio.CancelledError) as e:
        client = client_holder.get("client")
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.warning("ssh_exec failed to close client host={}", host)
        if check and isinstance(e, asyncio.TimeoutError):
            raise CommandError(-1, f"ssh command timed out after {timeout}s: {' '.join(cmd)}") from None
        raise
    if check and exit_status != 0:
        raise CommandError(exit_status, f"{' '.join(cmd)}")
    return result
