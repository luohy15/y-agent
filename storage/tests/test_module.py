"""Repository/service tests for module / module_version (todo 3020, phase 1 rename).

Runs against an isolated in-memory SQLite DB (not the real Postgres) so this
works under `unittest discover` in CI without a DATABASE_URL. setUp/tearDown
swap storage.database.base's engine/session factory and restore the
originals so this doesn't leak into other test modules run in the same
process.
"""

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import storage.database.base as dbbase
import storage.entity.module  # noqa: F401 - registers ModuleEntity with Base.metadata
import storage.entity.module_version  # noqa: F401 - registers ModuleVersionEntity with Base.metadata
import storage.entity.user  # noqa: F401 - module.user_id FKs to user.id
from storage.repository import module_version as version_repo
from storage.service import module as module_service
from storage.service.module import RollbackConflictError


class ModuleTestCase(unittest.TestCase):
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


class PublishTest(ModuleTestCase):
    def test_publish_increments_version_no_and_moves_pointer(self):
        module = module_service.create_module(1, "finance")

        v1 = module_service.publish(1, module.module_id, ui_sha256="aaa", ui_storage_key="module/finance/aaa.js")
        self.assertEqual(v1.version_no, 1)
        self.assertEqual(module_service.get_module(1, module.module_id).active_version_id, v1.version_id)

        v2 = module_service.publish(1, module.module_id, ui_sha256="bbb", ui_storage_key="module/finance/bbb.js")
        self.assertEqual(v2.version_no, 2)
        self.assertEqual(module_service.get_module(1, module.module_id).active_version_id, v2.version_id)

    def test_publish_one_row_carries_both_halves(self):
        """PRD atomicity: one publish = one version row spanning UI + API halves."""
        module = module_service.create_module(1, "finance")
        v1 = module_service.publish(
            1,
            module.module_id,
            ui_sha256="uihash",
            ui_storage_key="module/finance/uihash.js",
            api_sha256="apihash",
            api_storage_key="module/finance/apihash.api.zip",
            min_backend_version=1,
        )
        self.assertEqual(v1.version_no, 1)
        self.assertEqual(v1.ui_sha256, "uihash")
        self.assertEqual(v1.api_sha256, "apihash")
        self.assertEqual(v1.min_backend_version, 1)

        # A second publish replaces the active pointer; the previous row keeps
        # both of its original halves (no cross-publish mixing possible).
        v2 = module_service.publish(
            1,
            module.module_id,
            ui_sha256="ui2",
            ui_storage_key="module/finance/ui2.js",
            api_sha256="api2",
            api_storage_key="module/finance/api2.api.zip",
        )
        v1_after = version_repo.get_version_by_no(1, module.module_id, 1)
        self.assertEqual(v1_after.ui_sha256, "uihash")
        self.assertEqual(v1_after.api_sha256, "apihash")
        self.assertEqual(v2.ui_sha256, "ui2")
        self.assertEqual(v2.api_sha256, "api2")
        self.assertEqual(module_service.get_module(1, module.module_id).active_version_id, v2.version_id)

        # Rollback restores both halves of v1 together.
        rolled = module_service.rollback(1, module.module_id)
        self.assertEqual(rolled.active_version_id, v1.version_id)
        active = module_service.get_version(1, rolled.active_version_id)
        self.assertEqual(active.ui_sha256, "uihash")
        self.assertEqual(active.api_sha256, "apihash")

    def test_publish_no_activate_stages_without_moving_pointer(self):
        module = module_service.create_module(1, "finance")
        v1 = module_service.publish(1, module.module_id, ui_sha256="aaa", ui_storage_key="module/finance/aaa.js")
        v2 = module_service.publish(
            1, module.module_id, ui_sha256="bbb", ui_storage_key="module/finance/bbb.js", activate=False
        )
        self.assertEqual(v2.version_no, 2)
        self.assertEqual(module_service.get_module(1, module.module_id).active_version_id, v1.version_id)

    def test_second_publish_leaves_version_1_row_byte_identical(self):
        module = module_service.create_module(1, "finance")
        v1 = module_service.publish(
            1,
            module.module_id,
            ui_sha256="aaa",
            ui_storage_key="module/finance/aaa.js",
            label="Finance",
            icon="chart",
            description="[2412] initial publish",
        )
        module_service.publish(1, module.module_id, ui_sha256="bbb", ui_storage_key="module/finance/bbb.js")

        v1_after = version_repo.get_version_by_no(1, module.module_id, 1)
        self.assertEqual(v1_after.version_id, v1.version_id)
        self.assertEqual(v1_after.ui_sha256, "aaa")
        self.assertEqual(v1_after.ui_storage_key, "module/finance/aaa.js")
        self.assertEqual(v1_after.label, "Finance")
        self.assertEqual(v1_after.icon, "chart")
        self.assertEqual(v1_after.built_at, v1.built_at)
        self.assertEqual(v1_after.description, "[2412] initial publish")

    def test_publish_description_round_trips_through_list_versions(self):
        module = module_service.create_module(1, "finance")
        v1 = module_service.publish(
            1, module.module_id, ui_sha256="aaa", ui_storage_key="module/finance/aaa.js",
            description="[2991] fix overflow",
        )
        self.assertEqual(v1.description, "[2991] fix overflow")

        versions = module_service.list_versions(1, module.module_id)
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0].description, "[2991] fix overflow")

    def test_publish_to_unknown_module_returns_none_and_inserts_nothing(self):
        result = module_service.publish(1, "nope99", ui_sha256="aaa", ui_storage_key="module/x/aaa.js")
        self.assertIsNone(result)
        self.assertEqual(module_service.list_versions(1, "nope99"), [])


class RollbackTest(ModuleTestCase):
    def test_rollback_repoints_without_inserting_a_row(self):
        module = module_service.create_module(1, "finance")
        v1 = module_service.publish(1, module.module_id, ui_sha256="aaa", ui_storage_key="module/finance/aaa.js")
        module_service.publish(1, module.module_id, ui_sha256="bbb", ui_storage_key="module/finance/bbb.js")

        before = module_service.list_versions(1, module.module_id)
        self.assertEqual(len(before), 2)

        updated = module_service.rollback(1, module.module_id)
        self.assertEqual(updated.active_version_id, v1.version_id)

        after = module_service.list_versions(1, module.module_id)
        self.assertEqual(len(after), 2)

    def test_rollback_targets_greatest_version_below_current_across_a_gap(self):
        module = module_service.create_module(1, "finance")
        module_service.publish(1, module.module_id, ui_sha256="aaa", ui_storage_key="module/finance/aaa.js")
        module_service.publish(1, module.module_id, ui_sha256="bbb", ui_storage_key="module/finance/bbb.js")
        module_service.publish(1, module.module_id, ui_sha256="ccc", ui_storage_key="module/finance/ccc.js")
        # Simulate a pruned v4: jump straight to version_no 5.
        version_repo.create_version(
            1, version_id="v5", module_id=module.module_id, version_no=5,
            ui_sha256="eee", ui_storage_key="module/finance/eee.js",
        )
        module_service.activate(1, module.module_id, 5)

        updated = module_service.rollback(1, module.module_id)
        self.assertEqual(updated.active_version_id, version_repo.get_version_by_no(1, module.module_id, 3).version_id)

    def test_rollback_with_no_previous_version_is_a_noop(self):
        module = module_service.create_module(1, "finance")
        v1 = module_service.publish(1, module.module_id, ui_sha256="aaa", ui_storage_key="module/finance/aaa.js")
        result = module_service.rollback(1, module.module_id)
        self.assertIsNone(result)
        self.assertEqual(module_service.get_module(1, module.module_id).active_version_id, v1.version_id)

    def test_rollback_with_matching_from_version_id_succeeds(self):
        module = module_service.create_module(1, "finance")
        v1 = module_service.publish(1, module.module_id, ui_sha256="aaa", ui_storage_key="module/finance/aaa.js")
        v2 = module_service.publish(1, module.module_id, ui_sha256="bbb", ui_storage_key="module/finance/bbb.js")

        updated = module_service.rollback(1, module.module_id, from_version_id=v2.version_id)
        self.assertEqual(updated.active_version_id, v1.version_id)

    def test_rollback_conflict_when_active_pointer_has_moved(self):
        """A publish landing between the caller reading the active version and
        the rollback request must not let the request demote the newer
        version -- it should reject instead (S6 review finding)."""
        module = module_service.create_module(1, "finance")
        module_service.publish(1, module.module_id, ui_sha256="aaa", ui_storage_key="module/finance/aaa.js")
        v2 = module_service.publish(1, module.module_id, ui_sha256="bbb", ui_storage_key="module/finance/bbb.js")
        v3 = module_service.publish(1, module.module_id, ui_sha256="ccc", ui_storage_key="module/finance/ccc.js")

        with self.assertRaises(RollbackConflictError) as ctx:
            # Caller last saw v2 active (e.g. v2's mount failed and rendered a
            # failure card), but v3 has since been published and activated.
            module_service.rollback(1, module.module_id, from_version_id=v2.version_id)
        self.assertEqual(ctx.exception.active_version_id, v3.version_id)

        # The pointer must be untouched by the rejected call.
        self.assertEqual(module_service.get_module(1, module.module_id).active_version_id, v3.version_id)


class ActivateTest(ModuleTestCase):
    def test_activate_by_number_repoints_to_historical_version(self):
        module = module_service.create_module(1, "finance")
        v1 = module_service.publish(1, module.module_id, ui_sha256="aaa", ui_storage_key="module/finance/aaa.js")
        module_service.publish(1, module.module_id, ui_sha256="bbb", ui_storage_key="module/finance/bbb.js")
        module_service.publish(1, module.module_id, ui_sha256="ccc", ui_storage_key="module/finance/ccc.js")

        updated = module_service.activate(1, module.module_id, 1)
        self.assertEqual(updated.active_version_id, v1.version_id)

    def test_activate_unknown_version_no_returns_none(self):
        module = module_service.create_module(1, "finance")
        module_service.publish(1, module.module_id, ui_sha256="aaa", ui_storage_key="module/finance/aaa.js")
        self.assertIsNone(module_service.activate(1, module.module_id, 99))


class EnabledTest(ModuleTestCase):
    def test_set_enabled_toggles_without_touching_versions(self):
        module = module_service.create_module(1, "finance")
        module_service.publish(1, module.module_id, ui_sha256="aaa", ui_storage_key="module/finance/aaa.js")

        disabled = module_service.set_enabled(1, module.module_id, False)
        self.assertFalse(disabled.enabled)
        enabled = module_service.set_enabled(1, module.module_id, True)
        self.assertTrue(enabled.enabled)

        self.assertEqual(
            [v.version_no for v in module_service.list_versions(1, module.module_id)], [1]
        )


class DeleteTest(ModuleTestCase):
    def test_delete_removes_module_and_all_versions_and_returns_storage_keys(self):
        module = module_service.create_module(1, "finance")
        module_service.publish(
            1, module.module_id,
            ui_sha256="aaa", ui_storage_key="module/finance/aaa.js",
            api_sha256="aaaapi", api_storage_key="module/finance/aaa.api.zip",
        )
        module_service.publish(1, module.module_id, ui_sha256="bbb", ui_storage_key="module/finance/bbb.js")

        result = module_service.delete_module(1, module.module_id)
        self.assertEqual(
            sorted(result.storage_keys),
            ["module/finance/aaa.api.zip", "module/finance/aaa.js", "module/finance/bbb.js"],
        )
        # 2 version rows across which 3 objects are stored.
        self.assertEqual(result.version_count, 2)
        self.assertEqual(len(result.storage_keys), 3)

        self.assertIsNone(module_service.get_module(1, module.module_id))
        self.assertEqual(module_service.list_versions(1, module.module_id), [])

    def test_delete_unknown_module_returns_none(self):
        self.assertIsNone(module_service.delete_module(1, "nope99"))

    def test_delete_is_scoped_to_owner(self):
        mine = module_service.create_module(1, "finance")
        theirs = module_service.create_module(2, "finance")
        module_service.publish(2, theirs.module_id, ui_sha256="ccc", ui_storage_key="module/finance/ccc.js")

        self.assertIsNone(module_service.delete_module(1, theirs.module_id))
        self.assertIsNotNone(module_service.get_module(2, theirs.module_id))
        self.assertEqual(len(module_service.list_versions(2, theirs.module_id)), 1)

        result = module_service.delete_module(1, mine.module_id)
        self.assertEqual(result.version_count, 0)
        self.assertEqual(result.storage_keys, [])

    def test_delete_is_single_commit_both_rows_gone_together(self):
        """review finding 5: version + module rows must be gone in one transaction."""
        module = module_service.create_module(1, "finance")
        module_service.publish(
            1, module.module_id,
            ui_sha256="aaa", ui_storage_key="module/finance/aaa.js",
            api_sha256="api", api_storage_key="module/finance/api.api.zip",
        )
        result = module_service.delete_module(1, module.module_id)
        self.assertIsNotNone(result)
        # Both the module row and all version rows are deleted together.
        self.assertIsNone(module_service.get_module(1, module.module_id))
        self.assertEqual(module_service.list_versions(1, module.module_id), [])

    def test_create_after_delete_reuses_the_freed_slug(self):
        """Plan B5: hard delete must free UniqueConstraint(user_id, slug) so
        re-creating the same slug is a clean row, not a collision."""
        module = module_service.create_module(1, "finance")
        module_service.publish(1, module.module_id, ui_sha256="aaa", ui_storage_key="module/finance/aaa.js")
        module_service.delete_module(1, module.module_id)

        recreated = module_service.create_module(1, "finance")
        self.assertNotEqual(recreated.module_id, module.module_id)
        self.assertIsNone(recreated.active_version_id)
        self.assertEqual(module_service.list_versions(1, recreated.module_id), [])


class ListModulesTest(ModuleTestCase):
    def test_list_modules_enabled_only_filter(self):
        m1 = module_service.create_module(1, "finance")
        m2 = module_service.create_module(1, "todo")
        module_service.set_enabled(1, m2.module_id, False)

        all_modules = module_service.list_modules(1)
        self.assertEqual(sorted(m.module_id for m in all_modules), sorted([m1.module_id, m2.module_id]))

        enabled_only = module_service.list_modules(1, enabled_only=True)
        self.assertEqual([m.module_id for m in enabled_only], [m1.module_id])

    def test_slug_unique_per_owner_is_idempotent_via_create_module(self):
        first = module_service.create_module(1, "finance")
        second = module_service.create_module(1, "finance")
        self.assertEqual(first.module_id, second.module_id)

    def test_other_user_is_isolated(self):
        module_service.create_module(1, "finance")
        module_service.create_module(2, "finance")
        self.assertEqual(len(module_service.list_modules(1)), 1)
        self.assertEqual(len(module_service.list_modules(2)), 1)


class InitTablesModuleIsolationTest(unittest.TestCase):
    """Plan 4.4: init_tables() only ever touches storage.entity.base.Base's
    own metadata. A module entity declared against its own DeclarativeBase
    (loaded in the same process, as a warm API container would do) must
    neither be created by init_tables() nor break it.
    """

    def setUp(self):
        self._orig_engine = dbbase._engine
        self._orig_session_local = dbbase._SessionLocal
        self._engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        dbbase._engine = self._engine
        dbbase._SessionLocal = sessionmaker(bind=self._engine, expire_on_commit=False)

    def tearDown(self):
        dbbase._engine = self._orig_engine
        dbbase._SessionLocal = self._orig_session_local

    def test_module_owned_table_is_not_created_by_init_tables(self):
        from sqlalchemy import Column, Integer, inspect
        from sqlalchemy.orm import DeclarativeBase

        class ScratchModuleBase(DeclarativeBase):
            pass

        class ScratchWidget(ScratchModuleBase):
            __tablename__ = "scratch_widget"
            id = Column(Integer, primary_key=True)

        # A module entity registered on its own DeclarativeBase must never
        # appear on the host's Base.metadata, even once instantiated in the
        # same process.
        self.assertNotIn("scratch_widget", dbbase.Base.metadata.tables)

        dbbase.init_tables()  # must not raise

        table_names = inspect(self._engine).get_table_names()
        self.assertNotIn("scratch_widget", table_names)
        self.assertIn("user", table_names)
        self.assertIn("module", table_names)


if __name__ == "__main__":
    unittest.main()
