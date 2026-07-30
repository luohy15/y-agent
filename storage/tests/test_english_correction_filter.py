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
from storage.dto.chat import Chat, Message
from storage.entity.chat import ChatEntity
from storage.repository import chat as chat_repo
from storage.repository import english_correction as correction_repo
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

    def _insert_chat(self, chat_id, messages, updated_at_unix, raw_json=None):
        # json_content is persisted as json.dumps(Chat.to_dict()) — build it
        # through the real DTO so the fixture cannot drift from production.
        if raw_json is None:
            chat = Chat(
                id=chat_id,
                create_time=get_utc_iso8601_timestamp(),
                update_time=get_utc_iso8601_timestamp(),
                messages=[Message.from_dict(m) for m in messages],
            )
            raw_json = json.dumps(chat.to_dict())
        with dbbase.get_db() as session:
            entity = ChatEntity(
                user_id=1,
                chat_id=chat_id,
                json_content=raw_json,
                status="idle",
                unread=False,
            )
            entity.updated_at_unix = updated_at_unix
            entity.created_at_unix = updated_at_unix
            session.add(entity)
            session.flush()


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

    def test_skip_message_with_only_selection_block(self):
        text = " <selection>Someone else wrote these words in the selected text.</selection> "
        ok, reason = eng_service.is_eligible(_msg(content=text))
        self.assertFalse(ok)
        self.assertEqual(reason, "empty")

    def test_skip_selection_and_instruction_with_nothing_else(self):
        text = (
            "<selection>Someone else wrote these selected words.</selection>\n"
            "<instruction>Refine the grammar and wording while preserving meaning.</instruction>"
        )
        ok, reason = eng_service.is_eligible(_msg(content=text))
        self.assertFalse(ok)
        self.assertEqual(reason, "empty")

    def test_skip_unclosed_selection_block(self):
        text = "<selection>Someone else wrote this. I have my own eligible prose below."
        ok, reason = eng_service.is_eligible(_msg(content=text))
        self.assertFalse(ok)
        self.assertEqual(reason, "malformed_ui_wrapper")

    def test_nested_wrapper_blocks_are_removed_together(self):
        prose = "Can you check whether my own sentence is clear enough?"
        text = (
            "<selection>Quoted text <instruction>with nested boilerplate</instruction>.</selection>\n"
            f"{prose}"
        )
        normalized, reason = eng_service._eligible_text(_msg(content=text))
        self.assertEqual(normalized, prose)
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

    def test_skip_dispatch_prefix_without_trace_id(self):
        # Real shape seen live: routine fan-out dispatch relayed with no
        # trace-id, so the prefix has from:/from_chat:/to_chat: but no trace:.
        text = (
            "[from:manager from_chat:217696 to_chat:17990a]\n"
            "ticker=GOOGL repo=/Users/roy/luohy15 log_threshold=material"
        )
        ok, reason = eng_service.is_eligible(_msg(content=text))
        self.assertFalse(ok)
        self.assertEqual(reason, "dispatch_prefix")

    def test_skip_dispatch_prefix_variants(self):
        for text in (
            "[from:dev from_chat:aa to_chat:bb] look at todo 2871 please",
            "[to_chat:17990a] ticker=GOOGL repo=/Users/roy/luohy15",
            "[from:manager to:impl from_chat:aa] some relayed instruction here",
        ):
            ok, reason = eng_service.is_eligible(_msg(content=text))
            self.assertFalse(ok, text)
            self.assertEqual(reason, "dispatch_prefix", text)

    def test_skip_trace_prefix_with_prose_body(self):
        text = "[trace:2871 from:dev to:impl from_chat:aa to_chat:bb] I think we should refactor this"
        ok, reason = eng_service.is_eligible(_msg(content=text))
        self.assertFalse(ok)
        self.assertEqual(reason, "trace_prefix")

    def test_keep_bracketed_authored_prose(self):
        text = "[draft] can you review this before I send it out today?"
        ok, reason = eng_service.is_eligible(_msg(content=text))
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "ok")

    def test_skip_key_value_payload_without_prefix(self):
        text = "ticker=GOOGL repo=/Users/roy/luohy15 log_threshold=material"
        ok, reason = eng_service.is_eligible(_msg(content=text))
        self.assertFalse(ok)
        self.assertEqual(reason, "key_value_payload")

    def test_keep_prose_containing_equals_sign(self):
        text = "set DEBUG=true and it worked after I restarted the worker"
        ok, reason = eng_service.is_eligible(_msg(content=text))
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "ok")

    def test_keep_bracketed_prose_with_meta_key_and_space(self):
        # "to: " (colon followed by a space) is genuine prose, not a dispatch
        # prefix, which is always "to:" immediately followed by a non-space.
        text = "[note to: myself] remember to check the worker logs tomorrow morning"
        ok, reason = eng_service.is_eligible(_msg(content=text))
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "ok")

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

    def test_pending_reads_real_chat_to_dict_shape(self):
        """Regression: json_content is an object with a `messages` key, not a list."""
        now = get_unix_timestamp()
        msg = _msg(
            content="register a routine and run it once to see effects",
            mid="msg-3",
            ts=now - 20_000,
        )
        self._insert_chat("chat-3", [msg], updated_at_unix=now)

        with dbbase.get_db() as session:
            stored = json.loads(
                session.query(ChatEntity)
                .filter_by(chat_id="chat-3")
                .first()
                .json_content
            )
        self.assertIsInstance(stored, dict)
        self.assertIn("messages", stored)

        pending = eng_service.list_pending(1, since_unix=now - 60_000)
        self.assertEqual([m["message_id"] for m in pending["messages"]], ["msg-3"])
        self.assertEqual(pending["messages"][0]["text"], msg["content"])
        self.assertEqual(pending["scan_through_unix"], msg["unix_timestamp"])

    def test_pending_stores_only_prose_after_selection(self):
        now = get_unix_timestamp()
        prose = "Can you help me rewrite my own question more clearly?"
        msg = _msg(
            content=(
                "<selection>hi Roy! someone has a conflict on our Friday meeting.</selection>\n\n"
                f"{prose}"
            ),
            mid="msg-selection-prose",
            ts=now - 20_000,
        )
        self._insert_chat("chat-selection-prose", [msg], updated_at_unix=now)

        pending = eng_service.list_pending(1, since_unix=now - 60_000)

        self.assertEqual(len(pending["messages"]), 1)
        self.assertEqual(pending["messages"][0]["text"], prose)

    def test_pending_strips_multiple_wrapper_blocks(self):
        now = get_unix_timestamp()
        prose = "Please check whether my own sentence is clear enough."
        msg = _msg(
            content=(
                "<selection>First quoted passage from someone else.</selection>\n"
                "<instruction>Refine the grammar and wording.</instruction>\n"
                "<selection>Second quoted passage from someone else.</selection>\n"
                f"{prose}"
            ),
            mid="msg-multiple-wrappers",
            ts=now - 20_000,
        )
        self._insert_chat("chat-multiple-wrappers", [msg], updated_at_unix=now)

        pending = eng_service.list_pending(1, since_unix=now - 60_000)

        self.assertEqual(len(pending["messages"]), 1)
        self.assertEqual(pending["messages"][0]["text"], prose)

    def test_pending_reads_a_chat_written_by_the_real_writer(self):
        """End-to-end: production writer (_save_chat_sync) -> production reader."""
        now = get_unix_timestamp()
        msg = _msg(
            content="register a routine and run it once to see effects",
            mid="msg-e2e",
            ts=now - 15_000,
        )
        chat = Chat(
            id="chat-e2e",
            create_time=get_utc_iso8601_timestamp(),
            update_time=get_utc_iso8601_timestamp(),
            messages=[Message.from_dict(msg)],
        )
        chat_repo._save_chat_sync(1, chat)

        pending = eng_service.list_pending(1, since_unix=now - 60_000)
        self.assertEqual([m["message_id"] for m in pending["messages"]], ["msg-e2e"])
        self.assertEqual(pending["messages"][0]["chat_id"], "chat-e2e")
        self.assertGreater(pending["scan_through_unix"], pending["since_unix"])

    def test_pending_accepts_bare_list_json_content(self):
        now = get_unix_timestamp()
        msg = _msg(content="I already finish the draft today.", mid="msg-4", ts=now - 5_000)
        self._insert_chat(
            "chat-4", [msg], updated_at_unix=now, raw_json=json.dumps([msg])
        )
        pending = eng_service.list_pending(1, since_unix=now - 60_000)
        self.assertEqual([m["message_id"] for m in pending["messages"]], ["msg-4"])


class PendingBoundingTest(FilterTestCase):
    """The scan must stay bounded no matter how wide the window is."""

    def _seed(self, chats=6, per_chat=10, base=None):
        base = base or get_unix_timestamp() - 30 * 24 * 60 * 60 * 1000
        expected = []
        for c in range(chats):
            messages = []
            for i in range(per_chat):
                ts = base + (c * per_chat + i) * 1000
                mid = f"c{c}-m{i}"
                messages.append(
                    _msg(
                        content="I already finish the draft and will send you the PR.",
                        mid=mid,
                        ts=ts,
                    )
                )
                expected.append((ts, mid))
            self._insert_chat(f"chat-{c}", messages, updated_at_unix=base + 10**6)
        expected.sort()
        return base, expected

    def test_limit_returns_globally_oldest_candidates(self):
        base, expected = self._seed()
        pending = eng_service.list_pending(1, since_unix=base - 1, limit=7)

        self.assertEqual(len(pending["messages"]), 7)
        self.assertEqual(
            [m["message_id"] for m in pending["messages"]],
            [mid for _ts, mid in expected[:7]],
        )
        # Watermark advances to the batch max, so the remainder is picked up next run.
        self.assertEqual(pending["scan_through_unix"], expected[6][0])
        self.assertLess(pending["scan_through_unix"], expected[-1][0])

        eng_service.set_watermark(1, pending["scan_through_unix"])
        nxt = eng_service.list_pending(1, limit=7)
        self.assertEqual(
            [m["message_id"] for m in nxt["messages"]],
            [mid for _ts, mid in expected[7:14]],
        )

    def test_wide_window_does_not_scale_queries_with_candidates(self):
        """Dedup is one keyed query, not a lookup per candidate."""
        base, _expected = self._seed()
        calls = []
        original = correction_repo.find_by_message
        correction_repo.find_by_message = lambda *a, **kw: calls.append(a) or None
        try:
            pending = eng_service.list_pending(1, since_unix=base - 1, limit=5)
        finally:
            correction_repo.find_by_message = original

        self.assertEqual(len(pending["messages"]), 5)
        self.assertEqual(calls, [])

    def test_limit_is_clamped_to_max(self):
        base, _expected = self._seed(chats=2, per_chat=5)
        original_max = eng_service.MAX_LIMIT
        eng_service.MAX_LIMIT = 3
        try:
            pending = eng_service.list_pending(1, since_unix=base - 1, limit=10_000)
        finally:
            eng_service.MAX_LIMIT = original_max
        self.assertEqual(len(pending["messages"]), 3)


if __name__ == "__main__":
    unittest.main()
