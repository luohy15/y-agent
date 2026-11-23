"""Personal usage rows use an empty scope_id. Shared pre-cutover rows do not."""

PERSONAL_SCOPE_ID = ""
LEGACY_SCOPE_ID = "legacy-shared"


def personal_only(query, entity):
    return query.filter(entity.scope_id == PERSONAL_SCOPE_ID)
