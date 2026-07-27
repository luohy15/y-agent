"""Eligibility filter + watermark tests for english_correction (todo 2871, S2)."""

import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import storage.database.base as dbbase
import storage.entity.chat  # noqa: F401
import storage.entity.english_correction  # noqa: F401
import storage.entity.user  # noqa: F401
import storage.entity.user_preference  # noqa: F401
from storage.entity.chat import ChatEntity
from storage.service import english_correction as eng_service
from storage.util import get_unix_timestamp, get_utc_iso8601_timestamp


class FilterTestCase(unittest.TestCase):
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


def _msg(role="user", content="I already finish the draft today.", mid="m1", ts=None, **extra):
    now = get_unix_timestamp()
    base = {
        "role": role,
        "content": content,
        "id": mid,
        "timestamp": get_utc_iso8601_timestamp(),
        "unix_timestamp": ts if ts is not None else now,
    }
    base.update(extra)
    return base


class IsEligibleTest(FilterTestCase):
    def test_keep_plain_english(self):
        ok, reason = eng_service.is_eligible(_msg())
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_keep_majority_english_mixed(self):
        text = "先修一下, then I will push the fix after the tests pass."
        ok, reason = eng_service.is_eligible(_msg(content=text))
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "ok")

    def test_skip_assistant(self):
        ok, reason = eng_service.is_eligible(_msg(role="assistant"))
        self.assertFalse(ok)
        self.assertEqual(reason, "not_user")

    def test_skip_missing_id(self):
        m = _msg()
        del m["id"]
        ok, reason = eng_service.is_eligible(m)
        self.assertFalse(ok)
        self.assertEqual(reason, "missing_id")

    def test_skip_trace_prefix(self):
        text = "[trace:2871 from:dev to:impl from_chat:aa to_chat:bb] Look at todo 2871"
        ok, reason = eng_service.is_eligible(_msg(content=text))
        self.assertFalse(ok)
        self.assertEqual(reason, "trace_prefix")

    def test_skip_routine_prefix(self):
        text = "[routine:english-correction]\nlimit=50"
        ok, reason = eng_service.is_eligible(_msg(content=text))
        self.assertFalse(ok)
        self.assertEqual(reason, "routine_prefix")

    def test_skip_bootstrap(self):
        ok, reason = eng_service.is_eligible(_msg(content="load manager skill"))
        self.assertFalse(ok)
        self.assertEqual(reason, "bootstrap")

    def test_skip_code_block(self):
        text = "Here is the snippet:\n```python\nprint('hi')\n```\nand more words here"
        ok, reason = eng_service.is_eligible(_msg(content=text))
        self.assertFalse(ok)
        self.assertEqual(reason, "code_block")

    def test_skip_shell_command(self):
        ok, reason = eng_service.is_eligible(_msg(content="$ ls -la /tmp"))
        self.assertFalse(ok)
        self.assertEqual(reason, "shell")

    def test_skip_bare_path(self):
        ok, reason = eng_service.is_eligible(_msg(content="/Users/roy/luohy15/pages/plan.md"))
        self.assertFalse(ok)
        self.assertEqual(reason, "path")

    def test_skip_too_short(self):
        ok, reason = eng_service.is_eligible(_msg(content="ok done"))
        self.assertFalse(ok)
        self.assertEqual(reason, "too_short")

    def test_skip_majority_chinese(self):
        text = "今天把这个功能做完了，然后准备提交代码，晚上再看一下测试。"
        ok, reason = eng_service.is_eligible(_msg(content=text))
        self.assertFalse(ok)
        self.assertEqual(reason, "majority_non_english")


class WatermarkPendingTest(FilterTestCase):
    def _insert_chat(self, chat_id, messages, updated_at_unix):
        with dbbase.get_db() as session:
            entity = ChatEntity(
                user_id=1,
                chat_id=chat_id,
                json_content=json.dumps(messages),
                status="idle",
                unread=False,
            )
            entity.updated_at_unix = updated_at_unix
            entity.created_at_unix = updated_at_unix
            session.add(entity)
            session.flush()

    def test_pending_then_mark_scanned_excludes_message(self):
        now = get_unix_timestamp()
        msg = _msg(
            content="I already finish the draft and will send you the PR.",
            mid="msg-1",
            ts=now - 30_000,
        )
        self._insert_chat("chat-1", [msg], updated_at_unix=now)

        # No watermark: bootstrap lookback (1h) should still see the message
        first = eng_service.list_pending(1, limit=50)
        self.assertEqual(len(first["messages"]), 1)
        self.assertEqual(first["messages"][0]["message_id"], "msg-1")
        self.assertEqual(first["scan_through_unix"], msg["unix_timestamp"])

        eng_service.set_watermark(1, first["scan_through_unix"])
        self.assertEqual(eng_service.get_watermark(1), first["scan_through_unix"])

        second = eng_service.list_pending(1, limit=50)
        self.assertEqual(second["messages"], [])
        self.assertEqual(second["scan_through_unix"], first["scan_through_unix"])

    def test_pending_skips_already_stored_correction(self):
        now = get_unix_timestamp()
        msg = _msg(
            content="I already finish the draft and will send you the PR.",
            mid="msg-2",
            ts=now - 10_000,
        )
        self._insert_chat("chat-2", [msg], updated_at_unix=now)
        eng_service.add_correction(
            1,
            chat_id="chat-2",
            message_id="msg-2",
            message_at=msg["timestamp"],
            message_at_unix=msg["unix_timestamp"],
            original_text=msg["content"],
            corrected_text="I have already finished the draft and will send you the PR.",
            error_categories=["tense"],
            explanation="present perfect",
        )
        pending = eng_service.list_pending(1, since_unix=now - 60_000)
        self.assertEqual(pending["messages"], [])


if __name__ == "__main__":
    unittest.main()
