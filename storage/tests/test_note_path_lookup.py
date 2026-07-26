"""Repository tests for note.list_notes_at_path (todo 2888, S1: the filetree
rename note-pointer guard).

Runs against an isolated in-memory SQLite DB, same harness as
test_entity_tag.py, so this works under `unittest discover` without a
DATABASE_URL.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import storage.database.base as dbbase
import storage.entity.note  # noqa: F401 - registers NoteEntity with Base.metadata
import storage.entity.user  # noqa: F401 - note.user_id FKs to user.id
from storage.repository import note as note_repo


class NotePathLookupTestCase(unittest.TestCase):
    """Base class: points storage.database.base at a fresh in-memory SQLite DB."""

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


class ListNotesAtPathTest(NotePathLookupTestCase):
    def test_exact_match_hit(self):
        note_repo.save_note(1, note_repo.Note(note_id="n1", content_key="pages/plan-2888-filetree-rename.md"))
        results = note_repo.list_notes_at_path(1, "pages/plan-2888-filetree-rename.md")
        self.assertEqual([r.note_id for r in results], ["n1"])

    def test_descendant_hit_for_directory_key(self):
        note_repo.save_note(1, note_repo.Note(note_id="n1", content_key="pages/sub/a.md"))
        results = note_repo.list_notes_at_path(1, "pages/sub")
        self.assertEqual([r.note_id for r in results], ["n1"])

    def test_no_hit_when_path_is_only_a_string_prefix(self):
        note_repo.save_note(1, note_repo.Note(note_id="n1", content_key="pages/planax/a.md"))
        results = note_repo.list_notes_at_path(1, "pages/plan_x")
        self.assertEqual(results, [])

    def test_underscore_escaping_does_not_match_arbitrary_char(self):
        note_repo.save_note(1, note_repo.Note(note_id="n1", content_key="pages/plan_x/a.md"))
        results = note_repo.list_notes_at_path(1, "pages/plan_x")
        self.assertEqual([r.note_id for r in results], ["n1"])
        results = note_repo.list_notes_at_path(1, "pages/planZx")
        self.assertEqual(results, [])

    def test_percent_escaping_does_not_match_arbitrary_suffix(self):
        note_repo.save_note(1, note_repo.Note(note_id="n1", content_key="pages/100%done/a.md"))
        results = note_repo.list_notes_at_path(1, "pages/100%done")
        self.assertEqual([r.note_id for r in results], ["n1"])
        results = note_repo.list_notes_at_path(1, "pages/100")
        self.assertEqual(results, [])

    def test_soft_deleted_notes_excluded(self):
        note_repo.save_note(1, note_repo.Note(note_id="n1", content_key="pages/x.md"))
        note_repo.delete_note(1, "n1")
        results = note_repo.list_notes_at_path(1, "pages/x.md")
        self.assertEqual(results, [])

    def test_other_users_notes_excluded(self):
        note_repo.save_note(2, note_repo.Note(note_id="n1", content_key="pages/x.md"))
        results = note_repo.list_notes_at_path(1, "pages/x.md")
        self.assertEqual(results, [])

    def test_file_key_has_no_descendant_matches(self):
        note_repo.save_note(1, note_repo.Note(note_id="n1", content_key="pages/x.md/nested.md"))
        results = note_repo.list_notes_at_path(1, "pages/x.md")
        self.assertEqual([r.note_id for r in results], ["n1"])


if __name__ == "__main__":
    unittest.main()
