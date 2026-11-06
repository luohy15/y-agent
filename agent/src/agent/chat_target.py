"""Execution nodes a Claude Code chat may run on.

A node is a ``vm_config`` row (todo 4204): ``name`` is the id, ``vm_name`` its
SSH address and ``api_token`` its key. ``default`` is the orchestrator and the
jump anchor; every other row is reached through it with SSH ``direct-tcpip`` and
inherits the anchor's key when its own key is empty.

Resolution is strict: an unknown or disabled node raises instead of falling back
to the orchestrator. The layout is cached for a few seconds because a worker
touches it on every monitor pass; admission resolves uncached.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from storage.entity.dto import VmConfig


SSH_CONNECT_TIMEOUT_SECONDS = 30
LAYOUT_CACHE_SECONDS = 30
DEFAULT_NODE = "default"


class UnknownChatTarget(ValueError):
    """The name is not an owned vm_config node."""


class ChatTargetUnavailable(ValueError):
    """The node row exists but its address/key is unusable, or it is disabled."""


@dataclass(frozen=True)
class NodeTarget:
    """Everything a chat launch needs to know about one execution node."""

    name: str
    platform: str
    data_scope: str
    anchor: VmConfig
    node: VmConfig
    transport: str  # "vm" (direct) or "jump" (through the default anchor)
    user: Optional[str]
    host: Optional[str]
    port: Optional[int]
    tmp_dir: str
    tmux_socket: str
    tmux_binary: str
    claude_binary: str
    path: Optional[str]
    reaper: bool
    heartbeat: bool
    ingest_transcripts: bool
    supports_images: bool
    auth_mode: str  # "relay" (also the meaning of a NULL row) or "subscription"

    @property
    def work_dir(self) -> str:
        return self.node.work_dir or ""


@dataclass(frozen=True)
class StopTeardown:
    name: str
    transport: str
    host: Optional[str]
    port: Optional[int]
    user: Optional[str]
    command: str


_LAYOUT_CACHE: dict = {}


def clear_layout_cache() -> None:
    _LAYOUT_CACHE.clear()


def resolve_target(user_id: int, value: Optional[str], *, allow_disabled: bool = False) -> str:
    """Normalize a stored or requested node name and prove the row resolves.

    ``None``/``""``/``ec2`` all mean ``default``. Every target must have an
    owned registry row; environment configuration never substitutes for it.
    """
    from storage.service import vm_config as vm_service

    canonical = vm_service.normalize_node_name(value)
    try:
        vm_service.resolve_node(user_id, canonical, allow_disabled=allow_disabled)
    except vm_service.UnknownNode as exc:
        raise UnknownChatTarget(str(exc)) from exc
    except vm_service.NodeDisabled as exc:
        raise ChatTargetUnavailable(str(exc)) from exc
    return canonical


def layout(user_id: int, name: Optional[str], *, allow_disabled: bool = False,
           use_cache: bool = True) -> NodeTarget:
    """Build the descriptor for one node. Admission calls with ``use_cache=False``."""
    from storage.service import vm_config as vm_service

    canonical = vm_service.normalize_node_name(name)
    key = (user_id, canonical, allow_disabled)
    now = time.monotonic()
    if use_cache:
        cached = _LAYOUT_CACHE.get(key)
        if cached and cached[0] > now:
            return cached[1]
    target = _build_layout(user_id, canonical, allow_disabled)
    if use_cache:
        _LAYOUT_CACHE[key] = (now + LAYOUT_CACHE_SECONDS, target)
    return target


def _build_layout(user_id: int, name: str, allow_disabled: bool) -> NodeTarget:
    from storage.service import vm_config as vm_service

    anchor = vm_service.get_config(user_id, DEFAULT_NODE)
    if anchor is None:
        raise ChatTargetUnavailable("default node is not configured")

    node = vm_service.get_config(user_id, name)
    if node is None:
        raise UnknownChatTarget(f"unknown execution node: {name}")
    if not node.enabled and not allow_disabled:
        raise ChatTargetUnavailable(f"node is disabled: {name}")

    transport = "vm" if name == DEFAULT_NODE else "jump"
    platform = node.platform or "linux"
    data_scope = node.data_scope or "personal"

    if transport == "vm":
        user, host, port = _parse_address(anchor.vm_name) or (None, None, None)
    else:
        parsed = _parse_address(node.vm_name)
        if parsed is None:
            raise ChatTargetUnavailable(f"node {name} has no user@host:port address")
        user, host, port = parsed
        if not (node.api_token or anchor.api_token):
            raise ChatTargetUnavailable(f"node {name} has no ssh key")

    if platform == "darwin":
        if not user:
            raise ChatTargetUnavailable(f"darwin node {name} needs a user@host address")
        profile = {
            "tmp_dir": "/tmp",
            "tmux_binary": "/opt/homebrew/bin/tmux",
            "claude_binary": f"/Users/{user}/.local/bin/claude",
            "path": (
                f"/Users/{user}/.local/bin:/opt/homebrew/bin:/usr/local/bin:"
                "/usr/bin:/bin:/usr/sbin:/sbin"
            ),
            "reaper": False,
            "heartbeat": False,
        }
    else:
        profile = {
            "tmp_dir": "/tmp",
            "tmux_binary": "tmux",
            "claude_binary": "claude",
            "path": None,
            "reaper": transport == "vm",
            "heartbeat": True,
        }

    return NodeTarget(
        name=name,
        platform=platform,
        data_scope=data_scope,
        anchor=anchor,
        node=node,
        transport=transport,
        user=user,
        host=host,
        port=port,
        tmp_dir=profile["tmp_dir"],
        tmux_socket="y-agent",
        tmux_binary=profile["tmux_binary"],
        claude_binary=profile["claude_binary"],
        path=profile["path"],
        reaper=profile["reaper"],
        heartbeat=profile["heartbeat"],
        ingest_transcripts=transport == "vm",
        supports_images=transport == "vm",
        auth_mode=node.auth_mode if node.auth_mode in ("relay", "subscription") else "relay",
    )


def _parse_address(raw: Optional[str]) -> Optional[tuple[str, str, int]]:
    """Parse ``[ssh:]user@host:port``. Returns None when unusable."""
    if not raw:
        return None
    value = raw[len("ssh:"):] if raw.startswith("ssh:") else raw
    user, sep, hostport = value.partition("@")
    if not sep or not user or not hostport or "@" in hostport:
        return None
    host, port_sep, port_str = hostport.rpartition(":")
    if not port_sep or not host:
        return None
    try:
        port = int(port_str)
    except ValueError:
        return None
    if port <= 0:
        return None
    return user, host, port


def apply_launch(node: NodeTarget, cmd, env):
    """Point ``claude`` and PATH at this node. Other argv entries stay as given."""
    argv = list(cmd or [])
    if argv and argv[0] == "claude":
        argv[0] = node.claude_binary
    exported = dict(env or {})
    if node.path:
        exported["PATH"] = node.path
    return argv, exported


def _pkey(token: str):
    import io

    import paramiko

    return paramiko.Ed25519Key.from_private_key(io.StringIO(token))


def _connect(host, port, user, token, sock=None):
    import paramiko

    from agent.claude_code import _enable_keepalive

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        port=port,
        username=user,
        pkey=_pkey(token),
        sock=sock,
        timeout=SSH_CONNECT_TIMEOUT_SECONDS,
    )
    _enable_keepalive(client)
    return client


def connect_vm(vm_config):
    """Open the anchor session. Always wakes it: it is the tunnel host."""
    from agent.claude_code import _parse_ssh_target
    from agent.ec2_wake import ensure_and_touch_vm

    ensure_and_touch_vm(vm_config)
    user, host, port = _parse_ssh_target(vm_config.vm_name)
    return _connect(host, port, user, vm_config.api_token)


def open_jump_client(outer, node: NodeTarget):
    """Second SSH session through ``outer``'s direct-tcpip channel."""
    channel = outer.get_transport().open_channel(
        "direct-tcpip",
        (node.host, node.port),
        ("127.0.0.1", 0),
    )
    token = node.node.api_token or node.anchor.api_token
    return _connect(node.host, node.port, node.user, token, sock=channel)


def open_owned_client(node: NodeTarget):
    """One-shot client. Close it with ``close_owned_client`` (jump closes both)."""
    outer = connect_vm(node.anchor)
    if node.transport == "vm":
        return outer
    try:
        jump = open_jump_client(outer, node)
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


def build_stop_teardown(node: NodeTarget, chat_id: str) -> StopTeardown:
    from agent.claude_code import _kill_and_verify_cmd

    return StopTeardown(
        name=node.name,
        transport=node.transport,
        host=node.host,
        port=node.port,
        user=node.user,
        command=_kill_and_verify_cmd(chat_id, node=node),
    )
