"""Per-tenant object envelopes. Legacy keys stay plaintext bytes."""

from __future__ import annotations

import re

from storage.crypto.tenant import TenantCryptoError, encryption_active, open_stored, seal
from storage.crypto.tenant import key_state

_TENANT_KEY = re.compile(r"^(lifelog|notes|rss)/(\d+)/")


def link_prefix(user_id: int | None) -> str:
    if user_id is None:
        return "lifelog/link"
    return f"lifelog/{int(user_id)}/link"


def is_tenant_object_key(key: str) -> bool:
    return bool(key) and _TENANT_KEY.match(key) is not None


def is_link_object_key(key: str | None) -> bool:
    if not key or key.startswith(("/", "~")) or ".." in key.split("/"):
        return False
    if key.startswith("lifelog/link/"):
        return True
    return key.startswith("lifelog/") and "/link/" in key and is_tenant_object_key(key)


def rss_object_key(user_id: int, rss_feed_id: str, session=None) -> str:
    if session is not None and encryption_active(session, user_id):
        return f"rss/{int(user_id)}/{rss_feed_id}.xml"
    return f"rss/{rss_feed_id}.xml"


def note_object_key(user_id: int, note_id: str, session=None) -> str:
    if session is not None and encryption_active(session, user_id):
        return f"notes/{int(user_id)}/{note_id}/content.md"
    return f"notes/{note_id}/content.md"


def seal_body(key: str, body: bytes, *, session=None) -> bytes:
    match = _TENANT_KEY.match(key or "")
    if match is None:
        return body
    user_id = int(match.group(2))
    if session is None:
        from storage.database.base import get_db

        with get_db() as owned:
            return _seal(owned, user_id, key, body)
    return _seal(session, user_id, key, body)


def _seal(session, user_id: int, key: str, body: bytes) -> bytes:
    state = key_state(session, user_id)
    if state.kind != "active" or state.active is None:
        raise TenantCryptoError("encryption_inactive")
    token = seal(
        state.active.dek, user_id=user_id, table="s3", column=key, public_id=key,
        value=body.decode("utf-8"), key_id=state.active.key_id,
    )
    return token.encode("ascii")


def open_body(key: str, body: bytes, *, session=None) -> bytes:
    if not is_tenant_object_key(key):
        return body
    match = _TENANT_KEY.match(key)
    user_id = int(match.group(2))
    token = body.decode("utf-8")
    if session is None:
        from storage.database.base import get_db

        with get_db() as owned:
            opened = open_stored(
                owned, user_id=user_id, table="s3", column=key, public_id=key, value=token,
            )
    else:
        opened = open_stored(session, user_id=user_id, table="s3", column=key, public_id=key, value=token)
    if isinstance(opened, str):
        return opened.encode("utf-8")
    raise TenantCryptoError("tenant_crypto_malformed")
