"""User service."""

import os
from storage.repository.user import get_or_create_user

def get_cli_user_id() -> int:
    """Resolve the configured string user_id to the integer user.id PK."""
    env_val = os.getenv("Y_AGENT_USER_ID_DEV", os.getenv("Y_AGENT_USER_ID"))
    if env_val is not None:
        return int(env_val)
    return get_default_user_id()

def get_default_user_id() -> int:
    """Get the default user ID, creating a default user if necessary."""
    user = get_or_create_user("default")
    return user.id
