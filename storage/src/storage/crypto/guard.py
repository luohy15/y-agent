"""Fail-closed deploy guard for the configured keys and encrypted rows."""

from __future__ import annotations

from sqlalchemy import text

from storage.crypto.tenant import TenantCryptoError, master_keys
from storage.database.base import get_db

_TABLES = (
    "chat", "chat_wakeup", "todo", "entity_tag", "tag_vocabulary", "calendar_event",
    "reminder", "routine", "email", "email_account", "english_correction", "entity",
    "note", "link", "link_activity", "rss_feed", "bot_config", "vm_config",
    "user_cookies", "user_preference", "upload_job", "chat_context_session",
    "chat_context_request", "chat_context_contributor", "mcp_connector",
    "mcp_credential", "mcp_oauth_transaction",
)


def validate_master_key_ids(referenced) -> None:
    _, keys = master_keys()
    if any(not key_id or key_id not in keys for key_id in referenced):
        raise TenantCryptoError("tenant_master_key_unknown")


def encrypted_row_count() -> int:
    """Require the additive schema, available KEKs, and a key row for each owner."""
    total = 0
    with get_db() as session:
        referenced = session.execute(text('SELECT DISTINCT master_key_id FROM tenant_key')).scalars().all()
        validate_master_key_ids(referenced)
        for table in _TABLES:
            total += session.execute(text(f'SELECT count(*) FROM "{table}" WHERE enc_version = 1')).scalar() or 0
            owner = 't.user_id'
            source = f'"{table}" t'
            if table == "mcp_credential":
                source += ' LEFT JOIN mcp_connector c ON c.id = t.connector_pk'
                owner = 'c.user_id'
            missing = session.execute(text(
                f'SELECT count(*) FROM {source} WHERE t.enc_version = 1 AND NOT EXISTS '
                f'(SELECT 1 FROM tenant_key k WHERE k.user_id = {owner})'
            )).scalar()
            if missing:
                raise TenantCryptoError("tenant_key_missing")
    return int(total)
