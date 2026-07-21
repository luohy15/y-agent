"""Repository/service tests for entity_tag (todo 2838, S0 foundation).

Runs against an isolated in-memory SQLite DB (not the real Postgres) so this
works under `unittest discover` in CI without a DATABASE_URL. setUp/tearDown
swap storage.database.base's engine/session factory and restore the originals
so this doesn't leak into other test modules run in the same process.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import storage.database.base as dbbase
import storage.entity.entity  # noqa: F401 - registers EntityEntity with Base.metadata
import storage.entity.entity_tag  # noqa: F401 - registers EntityTagEntity with Base.metadata
import storage.entity.note  # noqa: F401 - registers NoteEntity with Base.metadata
import storage.entity.todo  # noqa: F401 - registers TodoEntity with Base.metadata
import storage.entity.user  # noqa: F401 - entity_tag.user_id FKs to user.id
from storage.entity.entity_tag import EntityTagEntity
from storage.repository import entity_tag as tag_repo
from storage.service import entity as entity_service
from storage.service import note as note_service
from storage.service import tag as tag_service
from storage.service import todo as todo_service


class EntityTagTestCase(unittest.TestCase):
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


class IndexMetadataTest(EntityTagTestCase):
    def test_composite_indexes_match_manual_migration(self):
        index_names = {idx.name for idx in EntityTagEntity.__table__.indexes}
        self.assertEqual(
            index_names,
            {"ix_entity_tag_user_tag", "ix_entity_tag_user_tag_pat", "ix_entity_tag_user_type_entity"},
        )

    def test_composite_index_columns(self):
        by_name = {idx.name: [c.name for c in idx.columns] for idx in EntityTagEntity.__table__.indexes}
        self.assertEqual(by_name["ix_entity_tag_user_tag"], ["user_id", "tag"])
        self.assertEqual(by_name["ix_entity_tag_user_tag_pat"], ["user_id", "tag"])
        self.assertEqual(by_name["ix_entity_tag_user_type_entity"], ["user_id", "entity_type", "entity_id"])

    def test_unique_constraint_columns(self):
        [uq] = [c for c in EntityTagEntity.__table__.constraints if c.__class__.__name__ == "UniqueConstraint"]
        self.assertEqual([c.name for c in uq.columns], ["user_id", "entity_type", "entity_id", "tag"])


class SyncTagsTest(EntityTagTestCase):
    def test_reconciles_add_and_remove(self):
        tag_repo.sync_tags(1, "todo", "t-1", ["work/y-agent", "meta/systems"])
        self.assertEqual(sorted(tag_repo.list_tags(1, "todo", "t-1")), ["meta/systems", "work/y-agent"])

        tag_repo.sync_tags(1, "todo", "t-1", ["work/y-agent", "life/health"])
        self.assertEqual(sorted(tag_repo.list_tags(1, "todo", "t-1")), ["life/health", "work/y-agent"])

    def test_sync_is_idempotent(self):
        tag_repo.sync_tags(1, "todo", "t-1", ["work/y-agent"])
        tag_repo.sync_tags(1, "todo", "t-1", ["work/y-agent"])
        self.assertEqual(tag_repo.list_tags(1, "todo", "t-1"), ["work/y-agent"])

    def test_sync_to_empty_removes_all(self):
        tag_repo.sync_tags(1, "todo", "t-1", ["work/y-agent"])
        tag_repo.sync_tags(1, "todo", "t-1", [])
        self.assertEqual(tag_repo.list_tags(1, "todo", "t-1"), [])


class AddRemoveTagTest(EntityTagTestCase):
    def test_add_tag_returns_false_on_duplicate(self):
        self.assertTrue(tag_repo.add_tag(1, "chat", "c-1", "work/y-agent"))
        self.assertFalse(tag_repo.add_tag(1, "chat", "c-1", "work/y-agent"))

    def test_remove_tag_returns_false_when_missing(self):
        self.assertFalse(tag_repo.remove_tag(1, "chat", "c-1", "work/y-agent"))
        tag_repo.add_tag(1, "chat", "c-1", "work/y-agent")
        self.assertTrue(tag_repo.remove_tag(1, "chat", "c-1", "work/y-agent"))
        self.assertFalse(tag_repo.remove_tag(1, "chat", "c-1", "work/y-agent"))

    def test_delete_for_entity_clears_all_tags(self):
        tag_repo.add_tag(1, "chat", "c-1", "work/y-agent")
        tag_repo.add_tag(1, "chat", "c-1", "life/health")
        self.assertEqual(tag_repo.delete_for_entity(1, "chat", "c-1"), 2)
        self.assertEqual(tag_repo.list_tags(1, "chat", "c-1"), [])


class FindByTagTest(EntityTagTestCase):
    def setUp(self):
        super().setUp()
        tag_repo.add_tag(1, "todo", "t-1", "work/y-agent")
        tag_repo.add_tag(1, "chat", "c-1", "work/y-agent")
        tag_repo.add_tag(1, "todo", "t-2", "work/finance")
        tag_repo.add_tag(2, "todo", "t-99", "work/y-agent")  # other user

    def test_exact_match_is_user_scoped(self):
        pairs = tag_repo.find_by_tag(1, "work/y-agent")
        self.assertEqual(sorted(pairs), [("chat", "c-1"), ("todo", "t-1")])

    def test_prefix_match_dedupes_multi_tag_entities(self):
        tag_repo.add_tag(1, "todo", "t-1", "work/other")  # second work/ tag on the same entity
        pairs = tag_repo.find_by_tag(1, "work/", prefix=True)
        self.assertEqual(sorted(pairs), [("chat", "c-1"), ("todo", "t-1"), ("todo", "t-2")])

    def test_other_user_is_isolated(self):
        self.assertEqual(tag_repo.find_by_tag(2, "work/y-agent"), [("todo", "t-99")])
        self.assertNotIn(("todo", "t-99"), tag_repo.find_by_tag(1, "work/y-agent"))


class VocabularyTest(EntityTagTestCase):
    def test_distinct_tags_counts_and_sorts(self):
        tag_repo.add_tag(1, "todo", "t-1", "work/y-agent")
        tag_repo.add_tag(1, "chat", "c-1", "work/y-agent")
        tag_repo.add_tag(1, "todo", "t-2", "life/health")
        self.assertEqual(tag_repo.distinct_tags(1), [("life/health", 1), ("work/y-agent", 2)])

    def test_service_list_vocabulary_delegates(self):
        tag_repo.add_tag(1, "todo", "t-1", "work/y-agent")
        self.assertEqual(tag_service.list_vocabulary(1), [("work/y-agent", 1)])


class GetByTagHydrationTest(EntityTagTestCase):
    def test_hydrates_todo_note_and_entity_via_their_own_services(self):
        todo = todo_service.create_todo(1, "Ship tag system")
        note = note_service.create_note(1, "pages/tag-system.md", front_matter={"tags": ["work/y-agent"]})
        entity = entity_service.create_entity(1, "y-agent", "project")

        tag_repo.add_tag(1, "todo", todo.todo_id, "work/y-agent")
        tag_repo.add_tag(1, "note", note.note_id, "work/y-agent")
        tag_repo.add_tag(1, "entity", entity.entity_id, "work/y-agent")

        grouped = tag_service.get_by_tag(1, "work/y-agent")

        self.assertEqual(grouped["todo"], [{"id": todo.todo_id, "title": "Ship tag system"}])
        self.assertEqual(grouped["note"], [{"id": note.note_id, "title": "pages/tag-system.md"}])
        self.assertEqual(grouped["entity"], [{"id": entity.entity_id, "title": "y-agent"}])

    def test_unregistered_entity_type_falls_back_to_id_only(self):
        tag_repo.add_tag(1, "chat", "c-1", "work/y-agent")
        grouped = tag_service.get_by_tag(1, "work/y-agent")
        self.assertEqual(grouped["chat"], [{"id": "c-1"}])


if __name__ == "__main__":
    unittest.main()
