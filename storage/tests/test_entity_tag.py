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


class NoteProjectionTest(EntityTagTestCase):
    """S1: front_matter.tags -> entity_tag on import/update, plus --tag list filter."""

    def test_import_projects_tags(self):
        note = note_service.import_note(1, "pages/x.md", front_matter={"tags": ["work/y-agent", "meta/systems"]})
        self.assertEqual(sorted(tag_repo.list_tags(1, "note", note.note_id)), ["meta/systems", "work/y-agent"])
        self.assertEqual(tag_service.get_by_tag(1, "work/y-agent")["note"], [{"id": note.note_id, "title": "pages/x.md"}])

    def test_reimport_reconciles_tags(self):
        note = note_service.import_note(1, "pages/x.md", front_matter={"tags": ["work/y-agent"]})
        note_service.import_note(1, "pages/x.md", front_matter={"tags": ["life/health"]})
        self.assertEqual(tag_repo.list_tags(1, "note", note.note_id), ["life/health"])

    def test_import_without_front_matter_does_not_touch_tags(self):
        note = note_service.import_note(1, "pages/x.md", front_matter={"tags": ["work/y-agent"]})
        note_service.import_note(1, "pages/x.md")
        self.assertEqual(tag_repo.list_tags(1, "note", note.note_id), ["work/y-agent"])

    def test_update_projects_tags(self):
        note = note_service.create_note(1, "pages/x.md", front_matter={"tags": ["work/y-agent"]})
        note_service.update_note(1, note.note_id, front_matter={"tags": ["life/health"]})
        self.assertEqual(tag_repo.list_tags(1, "note", note.note_id), ["life/health"])

    def test_list_notes_tag_filter(self):
        tagged = note_service.import_note(1, "pages/a.md", front_matter={"tags": ["work/y-agent"]})
        note_service.import_note(1, "pages/b.md", front_matter={"tags": ["life/health"]})
        results = note_service.list_notes(1, tag="work/y-agent")
        self.assertEqual([n.note_id for n in results], [tagged.note_id])

    def test_delete_note_clears_entity_tag_rows(self):
        note = note_service.import_note(1, "pages/a.md", front_matter={"tags": ["work/y-agent"]})
        note_service.delete_note(1, note.note_id)
        self.assertEqual(tag_repo.list_tags(1, "note", note.note_id), [])
        self.assertEqual(tag_service.get_by_tag(1, "work/y-agent"), {})
        self.assertEqual(tag_service.list_vocabulary(1), [])


class TodoProjectionTest(EntityTagTestCase):
    """S2: todo.tags -> entity_tag on create/update, plus --tag list filter."""

    def test_create_projects_tags(self):
        todo = todo_service.create_todo(1, "Ship it", tags=["work/y-agent", "meta/systems"])
        self.assertEqual(sorted(tag_repo.list_tags(1, "todo", todo.todo_id)), ["meta/systems", "work/y-agent"])
        self.assertEqual(tag_service.get_by_tag(1, "work/y-agent")["todo"], [{"id": todo.todo_id, "title": "Ship it"}])

    def test_update_reconciles_tags(self):
        todo = todo_service.create_todo(1, "Ship it", tags=["work/y-agent"])
        todo_service.update_todo(1, todo.todo_id, tags=["life/health"])
        self.assertEqual(tag_repo.list_tags(1, "todo", todo.todo_id), ["life/health"])

    def test_update_other_field_does_not_touch_tags(self):
        todo = todo_service.create_todo(1, "Ship it", tags=["work/y-agent"])
        todo_service.update_todo(1, todo.todo_id, desc="new desc")
        self.assertEqual(tag_repo.list_tags(1, "todo", todo.todo_id), ["work/y-agent"])

    def test_list_todos_tag_filter(self):
        tagged = todo_service.create_todo(1, "Ship it", tags=["work/y-agent"])
        todo_service.create_todo(1, "Other", tags=["life/health"])
        results = todo_service.list_todos(1, tag="work/y-agent")
        self.assertEqual([t.todo_id for t in results], [tagged.todo_id])


class EntityProjectionTest(EntityTagTestCase):
    """S3: entity.front_matter.tags -> entity_tag on import/update, plus --tag list filter."""

    def test_import_projects_tags(self):
        entity = entity_service.import_entity(1, "y-agent", "project", front_matter={"tags": ["work/y-agent"]})
        self.assertEqual(tag_repo.list_tags(1, "entity", entity.entity_id), ["work/y-agent"])
        self.assertEqual(tag_service.get_by_tag(1, "work/y-agent")["entity"], [{"id": entity.entity_id, "title": "y-agent"}])

    def test_reimport_reconciles_tags(self):
        entity = entity_service.import_entity(1, "y-agent", "project", front_matter={"tags": ["work/y-agent"]})
        entity_service.import_entity(1, "y-agent", "project", front_matter={"tags": ["life/health"]})
        self.assertEqual(tag_repo.list_tags(1, "entity", entity.entity_id), ["life/health"])

    def test_update_projects_tags(self):
        entity = entity_service.create_entity(1, "y-agent", "project", front_matter={"tags": ["work/y-agent"]})
        entity_service.update_entity(1, entity.entity_id, front_matter={"tags": ["life/health"]})
        self.assertEqual(tag_repo.list_tags(1, "entity", entity.entity_id), ["life/health"])

    def test_list_entities_tag_filter(self):
        tagged = entity_service.import_entity(1, "y-agent", "project", front_matter={"tags": ["work/y-agent"]})
        entity_service.import_entity(1, "other", "project", front_matter={"tags": ["life/health"]})
        results = entity_service.list_entities(1, tag="work/y-agent")
        self.assertEqual([e.entity_id for e in results], [tagged.entity_id])

    def test_delete_entity_clears_entity_tag_rows(self):
        entity = entity_service.import_entity(1, "y-agent", "project", front_matter={"tags": ["work/y-agent"]})
        entity_service.delete_entity(1, entity.entity_id)
        self.assertEqual(tag_repo.list_tags(1, "entity", entity.entity_id), [])
        self.assertEqual(tag_service.get_by_tag(1, "work/y-agent"), {})
        self.assertEqual(tag_service.list_vocabulary(1), [])


class GenericWriteCliServiceTest(EntityTagTestCase):
    """Underlying service.tag.add_tag/remove_tag exercised by the generic `y tag add/rm` CLI."""

    def test_add_then_remove_round_trip(self):
        self.assertTrue(tag_service.add_tag(1, "chat", "c-1", "work/y-agent"))
        self.assertEqual(tag_service.get_by_tag(1, "work/y-agent")["chat"], [{"id": "c-1"}])
        self.assertTrue(tag_service.remove_tag(1, "chat", "c-1", "work/y-agent"))
        self.assertEqual(tag_service.get_by_tag(1, "work/y-agent"), {})


class BackfillTagsTest(EntityTagTestCase):
    """S5: project pre-existing authoring-surface tags into entity_tag."""

    def _seed_without_projection(self):
        """Create note/entity/todo rows with tags but no entity_tag projection.

        create_todo always projects; note/entity create do not. For todos we
        wipe projection after create to simulate pre-entity_tag data.
        """
        note = note_service.create_note(
            1, "pages/backfill.md", front_matter={"tags": ["work/y-agent", "meta/systems"]}
        )
        entity = entity_service.create_entity(
            1, "backfill-entity", "project", front_matter={"tags": ["life/health"]}
        )
        todo = todo_service.create_todo(1, "Backfill todo", tags=["y-agent", "tags"])
        # Simulate pre-projection state: wipe entity_tag rows for the todo that create_todo wrote.
        tag_repo.delete_for_entity(1, "todo", todo.todo_id)
        self.assertEqual(tag_repo.list_tags(1, "note", note.note_id), [])
        self.assertEqual(tag_repo.list_tags(1, "entity", entity.entity_id), [])
        self.assertEqual(tag_repo.list_tags(1, "todo", todo.todo_id), [])
        return note, entity, todo

    def test_dry_run_does_not_write(self):
        note, entity, todo = self._seed_without_projection()
        result = tag_service.backfill_tags(1, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["by_type"]["note"]["with_tags"], 1)
        self.assertEqual(result["by_type"]["entity"]["with_tags"], 1)
        self.assertEqual(result["by_type"]["todo"]["with_tags"], 1)
        self.assertEqual(result["total_synced"], 3)
        self.assertEqual(tag_repo.list_tags(1, "note", note.note_id), [])
        self.assertEqual(tag_repo.list_tags(1, "entity", entity.entity_id), [])
        self.assertEqual(tag_repo.list_tags(1, "todo", todo.todo_id), [])

    def test_backfill_projects_all_three_carriers(self):
        note, entity, todo = self._seed_without_projection()
        result = tag_service.backfill_tags(1, dry_run=False)
        self.assertFalse(result["dry_run"])
        self.assertEqual(result["total_synced"], 3)
        self.assertEqual(
            sorted(tag_repo.list_tags(1, "note", note.note_id)),
            ["meta/systems", "work/y-agent"],
        )
        self.assertEqual(tag_repo.list_tags(1, "entity", entity.entity_id), ["life/health"])
        self.assertEqual(sorted(tag_repo.list_tags(1, "todo", todo.todo_id)), ["tags", "y-agent"])
        hydrated = tag_service.get_by_tag(1, "work/y-agent")
        self.assertEqual(hydrated["note"], [{"id": note.note_id, "title": "pages/backfill.md"}])

    def test_backfill_is_idempotent(self):
        self._seed_without_projection()
        tag_service.backfill_tags(1)
        first = tag_service.list_vocabulary(1)
        tag_service.backfill_tags(1)
        second = tag_service.list_vocabulary(1)
        self.assertEqual(first, second)

    def test_backfill_type_filter_and_limit(self):
        note_service.create_note(1, "pages/a.md", front_matter={"tags": ["work/a"]})
        note_service.create_note(1, "pages/b.md", front_matter={"tags": ["work/b"]})
        entity_service.create_entity(1, "e1", "project", front_matter={"tags": ["life/x"]})
        result = tag_service.backfill_tags(1, entity_types=["note"], limit=1)
        self.assertEqual(set(result["by_type"].keys()), {"note"})
        self.assertEqual(result["by_type"]["note"]["synced"], 1)
        self.assertEqual(result["total_synced"], 1)

    def test_backfill_skips_untagged_items(self):
        note_service.create_note(1, "pages/plain.md", front_matter={"title": "no tags"})
        todo_service.create_todo(1, "No tags")
        result = tag_service.backfill_tags(1, dry_run=True)
        self.assertEqual(result["by_type"]["note"]["with_tags"], 0)
        self.assertEqual(result["by_type"]["todo"]["with_tags"], 0)
        self.assertEqual(result["total_synced"], 0)


if __name__ == "__main__":
    unittest.main()
