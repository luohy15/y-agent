"""Repository/service tests for ui_artifact / ui_artifact_version (todo 2412, S2).

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
import storage.entity.ui_artifact  # noqa: F401 - registers UiArtifactEntity with Base.metadata
import storage.entity.ui_artifact_version  # noqa: F401 - registers UiArtifactVersionEntity with Base.metadata
import storage.entity.user  # noqa: F401 - ui_artifact.user_id FKs to user.id
from storage.repository import ui_artifact_version as version_repo
from storage.service import ui_artifact as artifact_service


class UiArtifactTestCase(unittest.TestCase):
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


class PublishTest(UiArtifactTestCase):
    def test_publish_increments_version_no_and_moves_pointer(self):
        artifact = artifact_service.create_artifact(1, "finance")

        v1 = artifact_service.publish(1, artifact.artifact_id, sha256="aaa", storage_key="ui/finance/aaa.js")
        self.assertEqual(v1.version_no, 1)
        self.assertEqual(artifact_service.get_artifact(1, artifact.artifact_id).active_version_id, v1.version_id)

        v2 = artifact_service.publish(1, artifact.artifact_id, sha256="bbb", storage_key="ui/finance/bbb.js")
        self.assertEqual(v2.version_no, 2)
        self.assertEqual(artifact_service.get_artifact(1, artifact.artifact_id).active_version_id, v2.version_id)

    def test_publish_no_activate_stages_without_moving_pointer(self):
        artifact = artifact_service.create_artifact(1, "finance")
        v1 = artifact_service.publish(1, artifact.artifact_id, sha256="aaa", storage_key="ui/finance/aaa.js")
        v2 = artifact_service.publish(
            1, artifact.artifact_id, sha256="bbb", storage_key="ui/finance/bbb.js", activate=False
        )
        self.assertEqual(v2.version_no, 2)
        self.assertEqual(artifact_service.get_artifact(1, artifact.artifact_id).active_version_id, v1.version_id)

    def test_second_publish_leaves_version_1_row_byte_identical(self):
        artifact = artifact_service.create_artifact(1, "finance")
        v1 = artifact_service.publish(
            1, artifact.artifact_id, sha256="aaa", storage_key="ui/finance/aaa.js", label="Finance", icon="chart"
        )
        artifact_service.publish(1, artifact.artifact_id, sha256="bbb", storage_key="ui/finance/bbb.js")

        v1_after = version_repo.get_version_by_no(1, artifact.artifact_id, 1)
        self.assertEqual(v1_after.version_id, v1.version_id)
        self.assertEqual(v1_after.sha256, "aaa")
        self.assertEqual(v1_after.storage_key, "ui/finance/aaa.js")
        self.assertEqual(v1_after.label, "Finance")
        self.assertEqual(v1_after.icon, "chart")
        self.assertEqual(v1_after.built_at, v1.built_at)


    def test_publish_to_unknown_artifact_returns_none_and_inserts_nothing(self):
        result = artifact_service.publish(1, "nope99", sha256="aaa", storage_key="ui/x/aaa.js")
        self.assertIsNone(result)
        self.assertEqual(artifact_service.list_versions(1, "nope99"), [])


class RollbackTest(UiArtifactTestCase):
    def test_rollback_repoints_without_inserting_a_row(self):
        artifact = artifact_service.create_artifact(1, "finance")
        v1 = artifact_service.publish(1, artifact.artifact_id, sha256="aaa", storage_key="ui/finance/aaa.js")
        artifact_service.publish(1, artifact.artifact_id, sha256="bbb", storage_key="ui/finance/bbb.js")

        before = artifact_service.list_versions(1, artifact.artifact_id)
        self.assertEqual(len(before), 2)

        updated = artifact_service.rollback(1, artifact.artifact_id)
        self.assertEqual(updated.active_version_id, v1.version_id)

        after = artifact_service.list_versions(1, artifact.artifact_id)
        self.assertEqual(len(after), 2)

    def test_rollback_targets_greatest_version_below_current_across_a_gap(self):
        artifact = artifact_service.create_artifact(1, "finance")
        artifact_service.publish(1, artifact.artifact_id, sha256="aaa", storage_key="ui/finance/aaa.js")
        artifact_service.publish(1, artifact.artifact_id, sha256="bbb", storage_key="ui/finance/bbb.js")
        artifact_service.publish(1, artifact.artifact_id, sha256="ccc", storage_key="ui/finance/ccc.js")
        # Simulate a pruned v4: jump straight to version_no 5.
        version_repo.create_version(
            1, version_id="v5", artifact_id=artifact.artifact_id, version_no=5,
            sha256="eee", storage_key="ui/finance/eee.js",
        )
        artifact_service.activate(1, artifact.artifact_id, 5)

        updated = artifact_service.rollback(1, artifact.artifact_id)
        self.assertEqual(updated.active_version_id, version_repo.get_version_by_no(1, artifact.artifact_id, 3).version_id)

    def test_rollback_with_no_previous_version_is_a_noop(self):
        artifact = artifact_service.create_artifact(1, "finance")
        v1 = artifact_service.publish(1, artifact.artifact_id, sha256="aaa", storage_key="ui/finance/aaa.js")
        result = artifact_service.rollback(1, artifact.artifact_id)
        self.assertIsNone(result)
        self.assertEqual(artifact_service.get_artifact(1, artifact.artifact_id).active_version_id, v1.version_id)


class ActivateTest(UiArtifactTestCase):
    def test_activate_by_number_repoints_to_historical_version(self):
        artifact = artifact_service.create_artifact(1, "finance")
        v1 = artifact_service.publish(1, artifact.artifact_id, sha256="aaa", storage_key="ui/finance/aaa.js")
        artifact_service.publish(1, artifact.artifact_id, sha256="bbb", storage_key="ui/finance/bbb.js")
        artifact_service.publish(1, artifact.artifact_id, sha256="ccc", storage_key="ui/finance/ccc.js")

        updated = artifact_service.activate(1, artifact.artifact_id, 1)
        self.assertEqual(updated.active_version_id, v1.version_id)

    def test_activate_unknown_version_no_returns_none(self):
        artifact = artifact_service.create_artifact(1, "finance")
        artifact_service.publish(1, artifact.artifact_id, sha256="aaa", storage_key="ui/finance/aaa.js")
        self.assertIsNone(artifact_service.activate(1, artifact.artifact_id, 99))


class EnabledTest(UiArtifactTestCase):
    def test_set_enabled_toggles_without_touching_versions(self):
        artifact = artifact_service.create_artifact(1, "finance")
        artifact_service.publish(1, artifact.artifact_id, sha256="aaa", storage_key="ui/finance/aaa.js")

        disabled = artifact_service.set_enabled(1, artifact.artifact_id, False)
        self.assertFalse(disabled.enabled)
        enabled = artifact_service.set_enabled(1, artifact.artifact_id, True)
        self.assertTrue(enabled.enabled)

        self.assertEqual(
            [v.version_no for v in artifact_service.list_versions(1, artifact.artifact_id)], [1]
        )


class ListArtifactsTest(UiArtifactTestCase):
    def test_list_artifacts_enabled_only_filter(self):
        a1 = artifact_service.create_artifact(1, "finance")
        a2 = artifact_service.create_artifact(1, "todo")
        artifact_service.set_enabled(1, a2.artifact_id, False)

        all_artifacts = artifact_service.list_artifacts(1)
        self.assertEqual(sorted(a.artifact_id for a in all_artifacts), sorted([a1.artifact_id, a2.artifact_id]))

        enabled_only = artifact_service.list_artifacts(1, enabled_only=True)
        self.assertEqual([a.artifact_id for a in enabled_only], [a1.artifact_id])

    def test_slug_unique_per_owner_is_idempotent_via_create_artifact(self):
        first = artifact_service.create_artifact(1, "finance")
        second = artifact_service.create_artifact(1, "finance")
        self.assertEqual(first.artifact_id, second.artifact_id)

    def test_other_user_is_isolated(self):
        artifact_service.create_artifact(1, "finance")
        artifact_service.create_artifact(2, "finance")
        self.assertEqual(len(artifact_service.list_artifacts(1)), 1)
        self.assertEqual(len(artifact_service.list_artifacts(2)), 1)


if __name__ == "__main__":
    unittest.main()
