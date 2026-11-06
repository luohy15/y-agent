"""VM configuration service.

`vm_config` rows are the execution-node registry (todo 4204). `default` is the
orchestrator and the SSH jump anchor; every other row is a chat-only node
dialed through it.
"""

import re
from typing import List, Optional
from storage.entity.dto import VmConfig
from storage.repository import vm_config as vm_repo


DEFAULT_NODE = "default"
NODE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
NODE_PLATFORMS = frozenset({"linux", "darwin"})
NODE_DATA_SCOPES = frozenset({"personal", "work"})
NODE_AUTH_MODES = frozenset({"relay", "subscription"})


class NodeError(ValueError):
    """Base for execution-node resolution and registry errors."""


class UnknownNode(NodeError):
    """No vm_config row owns this node name."""


class NodeDisabled(NodeError):
    """The node exists but is soft-disabled for new chats."""


class NodeProtected(NodeError):
    """The default node cannot be edited, disabled, or deleted."""


class NodeInUse(NodeError):
    """A chat still pins this node, so deleting it would orphan the snapshot."""


class InvalidNode(NodeError):
    """Malformed node name or metadata."""


def normalize_node_name(name: Optional[str]) -> str:
    """NULL, empty, and the legacy `ec2` id all mean the default node."""
    if name is None or name == "" or name == "ec2":
        return DEFAULT_NODE
    return name


def validate_node_name(name: str) -> str:
    if not isinstance(name, str) or not NODE_NAME_PATTERN.match(name):
        raise InvalidNode(f"invalid node name: {name!r}")
    return name


def resolve_node(user_id: int, name: Optional[str], *, allow_disabled: bool = False) -> VmConfig:
    """Strictly resolve one owned node row. No default or work-dir fallback.

    Unknown and disabled rows raise instead of substituting another machine:
    a caller that asked for a node must never silently land on the orchestrator.
    """
    canonical = normalize_node_name(name)
    config = vm_repo.get_config(user_id, canonical)
    if config is None:
        raise UnknownNode(f"unknown node: {canonical}")
    if not config.enabled and not allow_disabled:
        raise NodeDisabled(f"node is disabled: {canonical}")
    return config


def list_configs(user_id: int) -> List[VmConfig]:
    """All owned rows, default first, then name order."""
    return sorted(
        vm_repo.list_configs(user_id),
        key=lambda config: (config.name != DEFAULT_NODE, config.name),
    )


def list_user_ids_with_config(name: str = "default") -> List[int]:
    return vm_repo.list_user_ids_with_config(name)


def get_config(user_id: int, name: str = "default") -> Optional[VmConfig]:
    return vm_repo.get_config(user_id, name)


def set_config(user_id: int, config: VmConfig) -> VmConfig:
    return vm_repo.set_config(user_id, config)


def assign_auth_mode(config: VmConfig, existing: Optional[VmConfig], *, provided: bool) -> None:
    """Keep an omitted auth mode. A new row with none given defaults to relay.

    NULL stays NULL on an update that does not mention the field: launch treats
    NULL as relay. An explicit value must be in ``NODE_AUTH_MODES``.
    """
    if not provided:
        config.auth_mode = existing.auth_mode if existing is not None else "relay"
        return
    if config.auth_mode not in NODE_AUTH_MODES:
        raise InvalidNode(f"auth_mode must be one of {sorted(NODE_AUTH_MODES)}")


def set_node(user_id: int, config: VmConfig, *, api_token_provided: bool = True,
             enabled_provided: bool = True, auth_mode_provided: bool = False) -> VmConfig:
    """Create or update a non-default node.

    An omitted key inherits the default node's key (empty `api_token`), and an
    update that leaves the key out keeps the stored one. An omitted `enabled`
    keeps the stored value, so `y node add` does not re-enable a disabled node.
    An omitted `auth_mode` keeps the stored value; a new row defaults to relay.
    """
    canonical = validate_node_name(normalize_node_name(config.name))
    if canonical == DEFAULT_NODE:
        raise NodeProtected("refusing to edit the default node; it is the orchestrator")
    if config.platform not in (None, "") and config.platform not in NODE_PLATFORMS:
        raise InvalidNode(f"platform must be one of {sorted(NODE_PLATFORMS)}")
    if config.data_scope not in (None, "") and config.data_scope not in NODE_DATA_SCOPES:
        raise InvalidNode(f"data_scope must be one of {sorted(NODE_DATA_SCOPES)}")

    config.name = canonical
    config.platform = config.platform or None
    config.data_scope = config.data_scope or None
    existing = vm_repo.get_config(user_id, canonical)
    if not api_token_provided:
        config.api_token = existing.api_token if existing else ""
    if not enabled_provided:
        config.enabled = existing.enabled if existing else True
    assign_auth_mode(config, existing, provided=auth_mode_provided)
    return vm_repo.set_config(user_id, config)


def set_enabled(user_id: int, name: str, enabled: bool) -> VmConfig:
    canonical = normalize_node_name(name)
    if canonical == DEFAULT_NODE:
        raise NodeProtected("the default node cannot be disabled or enabled")
    config = vm_repo.set_enabled(user_id, canonical, enabled)
    if config is None:
        raise UnknownNode(f"unknown node: {canonical}")
    return config


def delete_node(user_id: int, name: str) -> bool:
    canonical = normalize_node_name(name)
    if canonical == DEFAULT_NODE:
        raise NodeProtected("the default node cannot be deleted")
    from storage.repository import chat as chat_repo

    if chat_repo.count_chats_with_execution_target(user_id, canonical):
        raise NodeInUse(f"node is still pinned by a chat: {canonical}")
    return vm_repo.delete_config(user_id, canonical)


def get_config_by_work_dir(user_id: int, work_dir: str) -> Optional[VmConfig]:
    return vm_repo.get_config_by_work_dir(user_id, work_dir)


def update_last_up(user_id: int, name: str, last_up: int) -> None:
    vm_repo.update_last_up(user_id, name, last_up)


def update_last_up_by_id(config_id: int, last_up: int) -> None:
    vm_repo.update_last_up_by_id(config_id, last_up)


def delete_config(user_id: int, name: str = "default") -> bool:
    return vm_repo.delete_config(user_id, name)
