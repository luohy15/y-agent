"""User service."""

import os
from storage.repository.user import get_or_create_user, list_users as repo_list_users


def list_users():
    return repo_list_users()

def get_cli_user_id() -> int:
    """Resolve the configured string user_id to the integer user.id PK."""
    env_val = os.getenv("Y_USER_ID_DEV", os.getenv("Y_USER_ID"))
    if env_val is not None:
        return int(env_val)
    return get_default_user_id()

def get_default_user_id() -> int:
    """Get the default user ID, creating a default user if necessary."""
    user = get_or_create_user("default")
    return user.id


def get_module_maintainer_user_id():
    """Resolve the configured module maintainer's public ID to its internal ID."""
    configured = os.environ.get("Y_AGENT_MODULE_MAINTAINER_USER_ID", "").strip()
    if not configured:
        return None
    from storage.repository.user import get_user_by_user_id

    user = get_user_by_user_id(configured)
    return user.id if user else None
