"""`chat.external_id` column authority (todo 2930 follow-up).

The `external_id` field is persisted twice: as a promoted column and inside the
`json_content` blob. `_entity_to_chat` must read the column, because the column
is the only side a manual migration can reach — nulling it is how a chat is told
"you have no resumable backend session". These tests lock that, plus the
fallback semantics of the other promoted fields, which are deliberately
different.
"""

import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import storage.database.base as dbbase
import storage.entity.chat  # noqa: F401
import storage.entity.user  # noqa: F401
from storage.dto.chat import Chat, Message
from storage.entity.chat import ChatEntity
from storage.repository import chat as chat_repo
from storage.util import get_unix_timestamp, get_utc_iso8601_timestamp

USER_ID = 1


def _chat_dto(chat_id="chat-1", external_id=None, backend=None, work_dir="/repo") -> Chat:
    return Chat(
        id=chat_id,
        create_time=get_utc_iso8601_timestamp(),
        update_time=get_utc_iso8601_timestamp(),
        messages=[
            Message(
                role="user",
                content="hello",
                timestamp=get_utc_iso8601_timestamp(),
                unix_timestamp=get_unix_timestamp(),
                id="m1",
            )
        ],
        external_id=external_id,
        backend=backend,
        work_dir=work_dir,
    )


class ExternalIdColumnAuthorityTest(unittest.TestCase):
    def setUp(self):
        self._orig_engine = dbbase._engine
        self._orig_session_local = dbbase._SessionLocal

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        dbbase.Base.metadata.create_all(bind=engine)
        dbbase._engine = engine
        dbbase._SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    def tearDown(self):
        dbbase._engine = self._orig_engine
        dbbase._SessionLocal = self._orig_session_local

    def _insert(self, chat_id, blob_dto, column_external_id, column_backend=None):
        """Insert a row whose column values can diverge from the blob's copy,
        the way a manual SQL migration leaves them."""
        with dbbase.get_db() as session:
            session.add(ChatEntity(
                user_id=USER_ID,
                chat_id=chat_id,
                title="t",
                json_content=json.dumps(blob_dto.to_dict()),
                external_id=column_external_id,
                backend=column_backend,
                status="idle",
            ))
            session.flush()

    def test_migrated_chat_reads_no_session_despite_stale_blob_copy(self):
        """The regression: migration 2930 nulled the column on 999 chats, the
        blob kept the foreign codex/grok session id, and the runtime resumed it."""
        self._insert(
            "chat-migrated",
            _chat_dto("chat-migrated", external_id="codex-thread-uuid", backend="codex"),
            column_external_id=None,
            column_backend="claude_code",
        )
        chat = chat_repo._get_chat_by_id_sync("chat-migrated")
        self.assertIsNone(chat.external_id)
        self.assertEqual(chat.backend, "claude_code")

    def test_column_wins_over_divergent_blob_copy(self):
        self._insert(
            "chat-diverged",
            _chat_dto("chat-diverged", external_id="stale-session"),
            column_external_id="live-session",
        )
        chat = chat_repo._get_chat_by_id_sync("chat-diverged")
        self.assertEqual(chat.external_id, "live-session")

    def test_empty_column_reads_as_no_session(self):
        """`y chat import-claude` wrote '' for rows with a malformed blob; an
        empty handle must normalize to None, not become a resume argument."""
        self._insert(
            "chat-empty",
            _chat_dto("chat-empty", external_id="stale-session"),
            column_external_id="",
        )
        chat = chat_repo._get_chat_by_id_sync("chat-empty")
        self.assertIsNone(chat.external_id)

    def test_other_promoted_fields_still_fall_back_to_the_blob(self):
        """Only `external_id` is read unconditionally. The metadata fields keep
        their `is not None` fallback, so a NULL column there still means
        "not promoted yet", not "empty"."""
        self._insert(
            "chat-meta",
            _chat_dto("chat-meta", external_id="live-session", backend="claude_code"),
            column_external_id="live-session",
            column_backend=None,
        )
        chat = chat_repo._get_chat_by_id_sync("chat-meta")
        self.assertEqual(chat.backend, "claude_code")

    def test_save_keeps_the_column_in_step_with_the_dto(self):
        """The read side can only be authoritative because every save writes the
        column, including when the handle is dropped."""
        chat = _chat_dto("chat-roundtrip", external_id="session-a")
        self._insert("chat-roundtrip", chat, column_external_id="session-a")

        chat.external_id = "session-b"
        chat_repo._save_chat_sync(USER_ID, chat)
        self.assertEqual(chat_repo._get_chat_by_id_sync("chat-roundtrip").external_id, "session-b")

        chat.external_id = None
        chat_repo._save_chat_sync(USER_ID, chat)
        with dbbase.get_db() as session:
            row = session.query(ChatEntity).filter_by(chat_id="chat-roundtrip").first()
            self.assertIsNone(row.external_id)
        self.assertIsNone(chat_repo._get_chat_by_id_sync("chat-roundtrip").external_id)


if __name__ == "__main__":
    unittest.main()
