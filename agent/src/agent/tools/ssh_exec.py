import asyncio
import io

import paramiko
from loguru import logger

from storage.entity.dto import VmConfig


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


async def ssh_exec(vm_config: VmConfig, cmd: list[str], stdin: str | None = None, dir: str | None = None, timeout: float = 30) -> str:
    user, host, port = _parse_ssh_target(vm_config.vm_name)
    key = paramiko.Ed25519Key.from_private_key(io.StringIO(vm_config.api_token))

    parts = []
    if dir:
        parts.append(f"cd {_shell_quote(dir)} &&")
    parts.append(" ".join(_shell_quote(c) for c in cmd))
    shell_cmd = " ".join(parts)

    logger.info("ssh_exec host={} port={} user={} cmd={}", host, port, user, shell_cmd)

    def _run():
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, port=port, username=user, pkey=key, timeout=timeout)

        stdin_ch, stdout_ch, stderr_ch = client.exec_command(shell_cmd, timeout=timeout)
        if stdin:
            stdin_ch.write(stdin)
        stdin_ch.close()

        result = stdout_ch.read().decode("utf-8", errors="replace")
        exit_status = stdout_ch.channel.recv_exit_status()
        client.close()

        logger.info("ssh_exec done exit_status={} stdout_len={}", exit_status, len(result))
        return result

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run)
