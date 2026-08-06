"""Regression tests for get_latest_marker (todo 3044).

Pins the writer/reader contract between update_todo's history note format and
the ast-based progress extractor used by get_latest_marker. Without these, a
format change in the f-string at update_todo silently returns None for every
entry, which the dev claim protocol reads as "todo is free".

Uses an in-memory SQLite DB (same pattern as test_entity_tag.py) so the real
update_todo path is exercised end-to-end under unittest discover.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import storage.database.base as dbbase
import storage.entity.todo  # noqa: F401 - registers TodoEntity with Base.metadata
import storage.entity.user  # noqa: F401 - todo.user_id FKs to user.id
from storage.entity.dto import Todo, TodoHistoryEntry
from storage.service import todo as todo_service
from storage.service.todo import _changed_progress_value, get_latest_marker


class TodoMarkerTestCase(unittest.TestCase):
    """Points storage.database.base at a fresh in-memory SQLite DB."""

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


class UpdateTodoRoundTripTest(TodoMarkerTestCase):
    """(a) Notes produced by the real update_todo path round-trip into get_latest_marker."""

    def test_real_update_todo_note_is_matched_by_get_latest_marker(self):
        todo = todo_service.create_todo(1, "marker contract")
        updated = todo_service.update_todo(
            1, todo.todo_id, progress="[dev-claim] CLAIM chat=abc123 at=2026-08-06 16:34"
        )
        self.assertIsNotNone(updated)
        claim = get_latest_marker(updated, "[dev-claim]")
        self.assertIsNotNone(claim)
        self.assertIn("changed: progress=", claim)
        self.assertIn("[dev-claim] CLAIM chat=abc123", claim)

        # Multi-field change: progress is not the first key in the note body.
        updated = todo_service.update_todo(
            1,
            todo.todo_id,
            status="active",
            progress="[dev-handoff] chat=abc123 done=x, next=y",
        )
        handoff = get_latest_marker(updated, "[dev-handoff]")
        self.assertIsNotNone(handoff)
        self.assertIn("[dev-handoff] chat=abc123", handoff)
        # status was also written; parser must still find progress among the kwargs.
        self.assertIn("status=", handoff)
        self.assertIn("progress=", handoff)


class MidProseMentionTest(unittest.TestCase):
    """(b) Progress prose that merely mentions a marker mid-sentence must not match."""

    def test_incidental_mid_prose_mention_does_not_match(self):
        history = [
            TodoHistoryEntry(
                timestamp="2026-08-06T08:34:41.534Z",
                unix_timestamp=1,
                action="updated",
                note="changed: progress='[dev-claim] CLAIM chat=e56b7f at=2026-08-06 16:34'",
            ),
            TodoHistoryEntry(
                timestamp="2026-08-06T08:40:17.297Z",
                unix_timestamp=2,
                action="updated",
                # The production regression: a later progress note whose prose only
                # mentions the markers, not as a leading token of the progress value.
                note=(
                    "changed: progress='Fixed post-deploy regression: get_latest_marker "
                    "matched any note containing [dev-claim]/[dev-handoff] mid-prose'"
                ),
            ),
        ]
        todo = Todo(todo_id="3044", name="marker match", history=history)

        claim = get_latest_marker(todo, "[dev-claim]")
        self.assertIsNotNone(claim)
        self.assertTrue(claim.startswith("2026-08-06T08:34:41.534Z "))
        self.assertIn("[dev-claim] CLAIM chat=e56b7f", claim)

        self.assertIsNone(get_latest_marker(todo, "[dev-handoff]"))


class ClaimHandoffReleaseTest(unittest.TestCase):
    """(c) After CLAIM → HANDOFF → RELEASE, claim resolves to RELEASE and handoff is recoverable."""

    def test_claim_handoff_release_markers_resolve_correctly(self):
        history = [
            TodoHistoryEntry(
                timestamp="t1",
                unix_timestamp=1,
                action="updated",
                note="changed: progress='[dev-claim] CLAIM chat=c1 at=t1'",
            ),
            TodoHistoryEntry(
                timestamp="t2",
                unix_timestamp=2,
                action="updated",
                note="changed: progress='[dev-handoff] chat=c1 done=x, next=y'",
            ),
            # Prose that mentions both markers must not displace either.
            TodoHistoryEntry(
                timestamp="t3",
                unix_timestamp=3,
                action="updated",
                note=(
                    "changed: progress='mid-run note mentioning [dev-claim] and "
                    "[dev-handoff] without being either'"
                ),
            ),
            TodoHistoryEntry(
                timestamp="t4",
                unix_timestamp=4,
                action="updated",
                note="changed: progress='[dev-claim] RELEASE chat=c1 at=t4'",
            ),
        ]
        todo = Todo(todo_id="1", name="claim protocol", history=history)

        claim = get_latest_marker(todo, "[dev-claim]")
        self.assertIsNotNone(claim)
        self.assertTrue(claim.startswith("t4 "))
        self.assertIn("[dev-claim] RELEASE", claim)

        handoff = get_latest_marker(todo, "[dev-handoff]")
        self.assertIsNotNone(handoff)
        self.assertTrue(handoff.startswith("t2 "))
        self.assertIn("[dev-handoff] chat=c1", handoff)


class ChangedProgressValueTest(unittest.TestCase):
    """Edge cases for the note-format parser that get_latest_marker depends on."""

    def test_parses_single_and_double_quoted_reprs(self):
        self.assertEqual(
            _changed_progress_value("changed: progress='[dev-claim] CLAIM'"),
            "[dev-claim] CLAIM",
        )
        self.assertEqual(
            _changed_progress_value('changed: progress="[dev-handoff] done"'),
            "[dev-handoff] done",
        )

    def test_parses_progress_when_not_first_field(self):
        note = "changed: status='active', progress='[dev-handoff] done=x, next=y'"
        self.assertEqual(
            _changed_progress_value(note),
            "[dev-handoff] done=x, next=y",
        )

    def test_embedded_comma_and_quote_round_trip(self):
        # Repr of a value that itself contains commas and a single quote.
        value = "done=a, b's next"
        note = f"changed: progress={value!r}"
        self.assertEqual(_changed_progress_value(note), value)

    def test_returns_none_for_non_changed_or_missing_progress(self):
        self.assertIsNone(_changed_progress_value("not a changed note"))
        self.assertIsNone(_changed_progress_value("changed: status='active'"))
        self.assertIsNone(_changed_progress_value("changed: progress=None"))
        self.assertIsNone(_changed_progress_value(""))

    def test_get_latest_marker_handles_empty_history_and_empty_notes(self):
        self.assertIsNone(get_latest_marker(Todo(todo_id="1", name="x", history=None), "[dev-claim]"))
        self.assertIsNone(get_latest_marker(Todo(todo_id="1", name="x", history=[]), "[dev-claim]"))
        todo = Todo(
            todo_id="1",
            name="x",
            history=[
                TodoHistoryEntry(timestamp="t0", unix_timestamp=0, action="created"),
                TodoHistoryEntry(timestamp="t1", unix_timestamp=1, action="updated", note=""),
                TodoHistoryEntry(
                    timestamp="t2",
                    unix_timestamp=2,
                    action="updated",
                    note="changed: status='active'",
                ),
            ],
        )
        self.assertIsNone(get_latest_marker(todo, "[dev-claim]"))


if __name__ == "__main__":
    unittest.main()
