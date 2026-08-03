import asyncio
import io

import paramiko
from loguru import logger

from storage.entity.dto import VmConfig
from agent.ec2_wake import ensure_and_touch_vm
from agent.tools.errors import CommandError


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
    ensure_and_touch_vm(vm_config)
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
    client_holder: dict[str, paramiko.SSHClient] = {}

    def _run():
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client_holder["client"] = client
        client.connect(host, port=port, username=user, pkey=key, timeout=timeout)

        stdin_ch, stdout_ch, stderr_ch = client.exec_command(shell_cmd, timeout=timeout)
        if stdin:
            stdin_ch.write(stdin)
        stdin_ch.close()

        result = stdout_ch.read().decode("utf-8", errors="replace")
        exit_status = stdout_ch.channel.recv_exit_status()
        client.close()

        logger.info("ssh_exec done exit_status={} stdout_len={}", exit_status, len(result))
        return result, exit_status

    loop = asyncio.get_event_loop()
    try:
        result, exit_status = await asyncio.wait_for(
            loop.run_in_executor(None, _run), timeout=timeout
        )
    except asyncio.TimeoutError:
        client = client_holder.get("client")
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.warning("ssh_exec failed to close client after timeout host={}", host)
        if check:
            raise CommandError(-1, f"ssh command timed out after {timeout}s: {' '.join(cmd)}") from None
        raise
    if check and exit_status != 0:
        raise CommandError(exit_status, f"{' '.join(cmd)}")
    return result
