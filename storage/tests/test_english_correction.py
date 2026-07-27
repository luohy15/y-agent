"""Repository/service tests for english_correction (todo 2871, S1).

Runs against an isolated in-memory SQLite DB so unittest discover works without
a DATABASE_URL.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import storage.database.base as dbbase
import storage.entity.english_correction  # noqa: F401
import storage.entity.user  # noqa: F401
import storage.entity.user_preference  # noqa: F401
from storage.service import english_correction as eng_service


class EnglishCorrectionTestCase(unittest.TestCase):
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


def _add(user_id=1, chat_id="c1", message_id="m1", **overrides):
    kwargs = dict(
        chat_id=chat_id,
        message_id=message_id,
        message_at="2026-07-27T03:42:00+00:00",
        message_at_unix=1722051720000,
        original_text="I already finish the draft.",
        corrected_text="I have already finished the draft.",
        error_categories=["tense"],
        explanation="Use present perfect with already.",
    )
    kwargs.update(overrides)
    return eng_service.add_correction(user_id, **kwargs)


class CrudTest(EnglishCorrectionTestCase):
    def test_add_and_get(self):
        row = _add()
        self.assertTrue(row.correction_id)
        self.assertEqual(row.chat_id, "c1")
        self.assertEqual(row.message_id, "m1")
        self.assertEqual(row.error_categories, ["tense"])
        self.assertFalse(row.dismissed)

        fetched = eng_service.get_correction(1, row.correction_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.original_text, "I already finish the draft.")
        # Public dict never exposes integer PK
        d = fetched.to_dict()
        self.assertNotIn("id", d)
        self.assertEqual(d["correction_id"], row.correction_id)

    def test_list_and_dismiss_filter(self):
        a = _add(message_id="m1")
        b = _add(message_id="m2", original_text="Please check a attached log.")
        eng_service.dismiss_correction(1, a.correction_id)

        active = eng_service.list_corrections(1, dismissed=False)
        self.assertEqual([r.correction_id for r in active], [b.correction_id])

        dismissed = eng_service.list_corrections(1, dismissed=True)
        self.assertEqual([r.correction_id for r in dismissed], [a.correction_id])

        all_rows = eng_service.list_corrections(1)
        self.assertEqual(len(all_rows), 2)

    def test_dismiss_unknown_returns_none(self):
        self.assertIsNone(eng_service.dismiss_correction(1, "nope"))

    def test_duplicate_chat_message_returns_existing(self):
        first = _add(message_id="m-dup")
        second = _add(
            message_id="m-dup",
            original_text="different text should be ignored",
            corrected_text="also ignored",
            error_categories=["article"],
            explanation="ignored",
        )
        self.assertEqual(first.correction_id, second.correction_id)
        self.assertEqual(second.original_text, first.original_text)
        self.assertEqual(len(eng_service.list_corrections(1)), 1)

    def test_category_filter(self):
        _add(message_id="m1", error_categories=["tense", "aspect"])
        _add(message_id="m2", error_categories=["article"])
        rows = eng_service.list_corrections(1, category="tense")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].message_id, "m1")

    def test_query_filter(self):
        _add(message_id="m1", original_text="I already finish the draft.")
        _add(message_id="m2", original_text="Please check a attached log.")
        rows = eng_service.list_corrections(1, query="attached")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].message_id, "m2")


if __name__ == "__main__":
    unittest.main()
