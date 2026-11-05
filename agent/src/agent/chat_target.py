"""Closed set of machines a Claude Code chat may run on.

``ec2`` is the worker's existing VM. ``mac`` is one jump from that VM:
``direct-tcpip`` to ``Y_AGENT_CHAT_MAC_TARGET``, authenticated with the same
``vm_config`` key the worker already uses for EC2. This module does not install
or rotate that key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


MAC_TARGET_ENV = "Y_AGENT_CHAT_MAC_TARGET"
MAC_PATH = (
    "/Users/roy/.local/bin:/opt/homebrew/bin:/usr/local/bin:"
    "/usr/bin:/bin:/usr/sbin:/sbin"
)
MAC_CLAUDE = "/Users/roy/.local/bin/claude"
MAC_TMUX = "/opt/homebrew/bin/tmux"
SSH_CONNECT_TIMEOUT_SECONDS = 30


class UnknownChatTarget(ValueError):
    """The id is not in the closed ec2/mac set."""


class ChatTargetUnavailable(ValueError):
    """``mac`` was asked for but the address env is missing or unusable."""


@dataclass(frozen=True)
class ChatTarget:
    id: str
    platform: str
    user: Optional[str]
    host: Optional[str]
    port: Optional[int]
    tmp_dir: str
    tmux_socket: str
    tmux_binary: str
    claude_binary: str
    path: Optional[str]
    wake: bool
    reaper: bool
    heartbeat: bool


@dataclass(frozen=True)
class StopTeardown:
    target: str
    host: Optional[str]
    port: Optional[int]
    user: Optional[str]
    command: str


def resolve_target(value: Optional[str]) -> str:
    """Normalize a stored or requested id. ``None`` is ec2. ``mac`` needs an address."""
    if value is None or value == "" or value == "ec2":
        return "ec2"
    if value == "mac":
        if not os.environ.get(MAC_TARGET_ENV):
            raise ChatTargetUnavailable(f"{MAC_TARGET_ENV} is unset")
        return "mac"
    raise UnknownChatTarget(f"unknown execution_target: {value}")


def _parse_mac_target(raw: str) -> tuple[str, str, int]:
    user, sep, hostport = raw.partition("@")
    if not sep or not user or not hostport or "@" in hostport:
        raise ChatTargetUnavailable(f"{MAC_TARGET_ENV} must be user@host:port")
    host, port_sep, port_str = hostport.rpartition(":")
    if not port_sep:
        raise ChatTargetUnavailable(f"{MAC_TARGET_ENV} must be user@host:port")
    try:
        port = int(port_str)
    except ValueError as exc:
        raise ChatTargetUnavailable(f"{MAC_TARGET_ENV} has no numeric port") from exc
    if not host or port <= 0:
        raise ChatTargetUnavailable(f"{MAC_TARGET_ENV} must be user@host:port")
    return user, host, port


def layout(target_id: Optional[str]) -> ChatTarget:
    target = resolve_target(target_id)
    if target == "ec2":
        return ChatTarget(
            id="ec2",
            platform="linux",
            user=None,
            host=None,
            port=None,
            tmp_dir="/tmp",
            tmux_socket="y-agent",
            tmux_binary="tmux",
            claude_binary="claude",
            path=None,
            wake=True,
            reaper=True,
            heartbeat=True,
        )
    user, host, port = _parse_mac_target(os.environ[MAC_TARGET_ENV])
    return ChatTarget(
        id="mac",
        platform="darwin",
        user=user,
        host=host,
        port=port,
        tmp_dir="/tmp",
        tmux_socket="y-agent",
        tmux_binary=MAC_TMUX,
        claude_binary=MAC_CLAUDE,
        path=MAC_PATH,
        wake=True,
        reaper=False,
        heartbeat=False,
    )


def apply_launch(target_id, cmd, env):
    """Point ``claude`` and PATH at this target. Other argv entries stay as given."""
    desc = layout(target_id)
    argv = list(cmd or [])
    if argv and argv[0] == "claude":
        argv[0] = desc.claude_binary
    exported = dict(env or {})
    if desc.path:
        exported["PATH"] = desc.path
    return argv, exported


def _pkey(vm_config):
    import io

    import paramiko

    return paramiko.Ed25519Key.from_private_key(io.StringIO(vm_config.api_token))


def _connect(host, port, user, pkey, sock=None):
    import paramiko

    from agent.claude_code import _enable_keepalive

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        port=port,
        username=user,
        pkey=pkey,
        sock=sock,
        timeout=SSH_CONNECT_TIMEOUT_SECONDS,
    )
    _enable_keepalive(client)
    return client


def connect_vm(vm_config):
    """Open the worker's EC2 session. Always wakes that host: it is the tunnel."""
    from agent.claude_code import _parse_ssh_target
    from agent.ec2_wake import ensure_and_touch_vm

    ensure_and_touch_vm(vm_config)
    user, host, port = _parse_ssh_target(vm_config.vm_name)
    return _connect(host, port, user, _pkey(vm_config))


def open_jump_client(outer, vm_config, desc: ChatTarget):
    """Second SSH session through ``outer``'s direct-tcpip channel."""
    channel = outer.get_transport().open_channel(
        "direct-tcpip",
        (desc.host, desc.port),
        ("127.0.0.1", 0),
    )
    return _connect(desc.host, desc.port, desc.user, _pkey(vm_config), sock=channel)


def open_owned_client(vm_config, target: str = "ec2"):
    """One-shot client. Close it with ``close_owned_client`` (jump closes both)."""
    desc = layout(target)
    outer = connect_vm(vm_config)
    if desc.id == "ec2":
        return outer
    try:
        jump = open_jump_client(outer, vm_config, desc)
    except Exception:
        outer.close()
        raise
    jump._y_agent_outer = outer
    return jump


def close_owned_client(client) -> None:
    if client is None:
        return
    outer = getattr(client, "_y_agent_outer", None)
    try:
        client.close()
    finally:
        if outer is not None:
            try:
                outer.close()
            except Exception:
                pass


def build_stop_teardown(target_id: Optional[str], chat_id: str) -> StopTeardown:
    desc = layout(target_id)
    from agent.claude_code import _kill_and_verify_cmd

    return StopTeardown(
        target=desc.id,
        host=desc.host,
        port=desc.port,
        user=desc.user,
        command=_kill_and_verify_cmd(chat_id, target=desc.id),
    )
