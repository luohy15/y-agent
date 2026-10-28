"""Closed chat roles and the transition mapping for legacy callers."""

ROOT_ROLE = "manager"
COORDINATOR_ROLE = "leader"
ROLES = frozenset({ROOT_ROLE, COORDINATOR_ROLE})


def legacy_topic_to_role(topic):
    if topic == ROOT_ROLE:
        return ROOT_ROLE
    if topic in (COORDINATOR_ROLE, "dev"):
        return COORDINATOR_ROLE
    return None


def effective_role(role, topic):
    """Read old and new writers without resurrecting archived sessions."""
    if topic and topic.endswith("-archived"):
        return None
    return role or legacy_topic_to_role(topic)


def validate_role(role):
    if role is not None and role not in ROLES:
        raise ValueError("role must be manager or leader")
    return role
