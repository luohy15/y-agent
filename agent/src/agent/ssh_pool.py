"""SSH connection pool — reuse connections to the same host.

Keys are the EC2 endpoint, plus one jump client per mac target. The outer EC2
client stays in the pool for as long as any jump that was opened through it.
"""

import io
from typing import Dict, Tuple

import paramiko
from loguru import logger

from agent.claude_code import _enable_keepalive, _parse_ssh_target
from agent.ec2_wake import ensure_and_touch_vm


SSH_CONNECT_TIMEOUT_SECONDS = 30


class SSHPool:
    """Pool SSH connections keyed by (host, port, user), or mac jump identity.

    Usage:
        pool = SSHPool()
        client = pool.get_or_create(vm_config)
        client = pool.get_or_create(vm_config, target="mac")
        pool.close_all()  # at shutdown
    """

    def __init__(self):
        self._clients: Dict[Tuple, paramiko.SSHClient] = {}

    def _make_key(self, vm_config) -> Tuple[str, int, str]:
        user, host, port = _parse_ssh_target(vm_config.vm_name)
        return (host, port, user or "")

    def _discard(self, key) -> None:
        client = self._clients.pop(key, None)
        if client is None:
            return
        try:
            client.close()
        except Exception:
            pass

    def _drop_jumps(self) -> None:
        for key in [item for item in self._clients if item and item[0] == "mac"]:
            self._discard(key)

    def _get_or_create_vm(self, vm_config) -> paramiko.SSHClient:
        key = self._make_key(vm_config)
        client = self._clients.get(key)
        if client:
            transport = client.get_transport()
            if transport and transport.is_active():
                return client
            logger.info("ssh_pool: stale connection to {}:{}, reconnecting", key[0], key[1])
            self._discard(key)
            self._drop_jumps()

        ensure_and_touch_vm(vm_config)

        user, host, port = _parse_ssh_target(vm_config.vm_name)
        key_obj = paramiko.Ed25519Key.from_private_key(io.StringIO(vm_config.api_token))

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            host,
            port=port,
            username=user,
            pkey=key_obj,
            timeout=SSH_CONNECT_TIMEOUT_SECONDS,
        )
        _enable_keepalive(client)

        self._clients[key] = client
        logger.info("ssh_pool: new connection to {}:{} (pool size={})", host, port, len(self._clients))
        return client

    def get_or_create(self, vm_config, target: str = "ec2") -> paramiko.SSHClient:
        """Get an existing connection or create one for this chat target."""
        from agent.chat_target import layout, open_jump_client

        desc = layout(target)
        if desc.id == "ec2":
            return self._get_or_create_vm(vm_config)

        key = ("mac", desc.host, desc.port, desc.user or "")
        client = self._clients.get(key)
        if client:
            transport = client.get_transport()
            if transport and transport.is_active():
                return client
            logger.info("ssh_pool: stale mac jump to {}:{}, reconnecting", desc.host, desc.port)
            self._discard(key)

        outer = self._get_or_create_vm(vm_config)
        jump = open_jump_client(outer, vm_config, desc)
        self._clients[key] = jump
        logger.info("ssh_pool: new mac jump to {}:{} (pool size={})", desc.host, desc.port, len(self._clients))
        return jump

    def close_all(self):
        """Close jump clients first, then the EC2 sessions they depend on."""
        self._drop_jumps()
        for client in self._clients.values():
            try:
                client.close()
            except Exception:
                pass
        self._clients.clear()
        logger.info("ssh_pool: closed all connections")
