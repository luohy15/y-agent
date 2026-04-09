"""SSH connection pool — reuse connections to the same host."""

import io
from typing import Dict, Tuple

import paramiko
from loguru import logger

from agent.claude_code import _parse_ssh_target


class SSHPool:
    """Pool SSH connections keyed by (host, port, user).

    Usage:
        pool = SSHPool()
        client = pool.get_or_create(vm_config)
        # ... use client ...
        pool.close_all()  # at shutdown
    """

    def __init__(self):
        self._clients: Dict[Tuple[str, int, str], paramiko.SSHClient] = {}

    def _make_key(self, vm_config) -> Tuple[str, int, str]:
        user, host, port = _parse_ssh_target(vm_config.vm_name)
        return (host, port, user or "")

    def get_or_create(self, vm_config) -> paramiko.SSHClient:
        """Get existing connection or create new one."""
        key = self._make_key(vm_config)

        client = self._clients.get(key)
        if client:
            # Check if connection is still alive
            transport = client.get_transport()
            if transport and transport.is_active():
                return client
            else:
                # Dead connection, remove and recreate
                logger.info("ssh_pool: stale connection to {}:{}, reconnecting", key[0], key[1])
                try:
                    client.close()
                except Exception:
                    pass
                del self._clients[key]

        # Create new connection
        user, host, port = _parse_ssh_target(vm_config.vm_name)
        key_obj = paramiko.Ed25519Key.from_private_key(io.StringIO(vm_config.api_token))

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, port=port, username=user, pkey=key_obj)

        self._clients[key] = client
        logger.info("ssh_pool: new connection to {}:{} (pool size={})", host, port, len(self._clients))
        return client

    def close_all(self):
        """Close all pooled connections."""
        for key, client in self._clients.items():
            try:
                client.close()
            except Exception:
                pass
        self._clients.clear()
        logger.info("ssh_pool: closed all connections")
