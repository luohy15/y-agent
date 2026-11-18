"""Count enc_version=1 rows. A missing column means the feature is not applied yet."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from storage.database.base import get_db

_TABLES = (
    "chat", "chat_wakeup", "todo", "entity_tag", "tag_vocabulary", "calendar_event",
    "reminder", "routine", "email", "email_account", "english_correction", "entity",
    "note", "link", "link_activity", "rss_feed", "bot_config", "vm_config",
    "user_cookies", "user_preference", "upload_job", "chat_context_session",
    "chat_context_request", "chat_context_contributor", "mcp_connector",
    "mcp_credential", "mcp_oauth_transaction",
)


def encrypted_row_count() -> int:
    total = 0
    with get_db() as session:
        for table in _TABLES:
            try:
                with session.begin_nested():
                    total += session.execute(text(f'SELECT count(*) FROM "{table}" WHERE enc_version = 1')).scalar() or 0
            except ProgrammingError:
                continue
    return int(total)
