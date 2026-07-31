"""Unit tests for api.controller.ui_artifact (todo 2412, S3).

storage.service.ui_artifact and the bundle I/O helpers are mocked; nothing
touches a real database or S3.
"""

import hashlib
import io
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, UploadFile

from api.controller import ui_artifact as ctrl
from storage.dto.ui_artifact import UiArtifact
from storage.dto.ui_artifact_version import UiArtifactVersion


def _request(user_id=123):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id))


def _artifact(**overrides):
    base = dict(artifact_id="art_a1", slug="finance")
    base.update(overrides)
    return UiArtifact(**base)


def _version(**overrides):
    base = dict(
        version_id="ver_a1",
        artifact_id="art_a1",
        version_no=1,
        sha256="aaa",
        storage_key="ui/art_a1/aaa.js",
    )
    base.update(overrides)
    return UiArtifactVersion(**base)


def _upload(content: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename="bundle.js")


class CreateTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_returns_artifact_without_integer_ids(self):
        with patch.object(ctrl.ui_service, "create_artifact", return_value=_artifact()) as create_fn:
            result = await ctrl.create_artifact(ctrl.CreateRequest(slug="finance"), _request())
        create_fn.assert_called_once_with(123, "finance", kind="panel")
        self.assertEqual(result["artifact_id"], "art_a1")
        self.assertNotIn("id", result)
        self.assertNotIn("user_id", result)

    async def test_create_rejects_invalid_slug(self):
        for bad in ["", "Finance", "-lead", "has space", "under_score", "../x", "a" * 64]:
            with patch.object(ctrl.ui_service, "create_artifact") as create_fn:
                with self.assertRaises(HTTPException) as ctx:
                    await ctrl.create_artifact(ctrl.CreateRequest(slug=bad), _request())
            self.assertEqual(ctx.exception.status_code, 400, bad)
            create_fn.assert_not_called()

    async def test_create_rejects_unknown_kind(self):
        with patch.object(ctrl.ui_service, "create_artifact") as create_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.create_artifact(ctrl.CreateRequest(slug="finance", kind="page"), _request())
        self.assertEqual(ctx.exception.status_code, 400)
        create_fn.assert_not_called()


class ListTest(unittest.IsolatedAsyncioTestCase):
    async def test_list_joins_active_version_and_omits_integer_ids(self):
        artifact = _artifact(active_version_id="ver_a1")
        version = _version()
        with patch.object(ctrl.ui_service, "list_artifacts", return_value=[artifact]), \
             patch.object(ctrl.ui_service, "get_version", return_value=version):
            result = await ctrl.list_artifacts(_request(), enabled_only=False)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["active_version"]["version_id"], "ver_a1")
        self.assertNotIn("id", result[0])
        self.assertNotIn("user_id", result[0])
        self.assertNotIn("id", result[0]["active_version"])

    async def test_list_no_active_version_returns_null(self):
        with patch.object(ctrl.ui_service, "list_artifacts", return_value=[_artifact()]), \
             patch.object(ctrl.ui_service, "get_version") as get_fn:
            result = await ctrl.list_artifacts(_request())
        get_fn.assert_not_called()
        self.assertIsNone(result[0]["active_version"])


class PublishTest(unittest.IsolatedAsyncioTestCase):
    async def test_hash_mismatch_is_rejected(self):
        content = b"export default () => null;"
        bad_hash = "0" * 64
        with patch.object(ctrl.ui_service, "get_artifact", return_value=_artifact()), \
             patch.object(ctrl.ui_service, "publish") as pub_fn, \
             patch.object(ctrl, "_write_bundle") as write_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.publish(_request(), _upload(content), "art_a1", bad_hash)
        self.assertEqual(ctx.exception.status_code, 400)
        pub_fn.assert_not_called()
        write_fn.assert_not_called()

    async def test_hash_compare_is_case_insensitive(self):
        content = b"export default 42;"
        sha = hashlib.sha256(content).hexdigest().upper()
        version = _version(version_no=3, sha256=sha.lower(), storage_key=f"ui/art_a1/{sha.lower()}.js")
        with patch.object(ctrl.ui_service, "get_artifact", return_value=_artifact()), \
             patch.object(ctrl.ui_service, "publish", return_value=version), \
             patch.object(ctrl, "_write_bundle"):
            result = await ctrl.publish(_request(), _upload(content), "art_a1", sha)
        self.assertEqual(result["version_no"], 3)

    async def test_publish_writes_bundle_before_inserting_version(self):
        content = b"export default 42;"
        sha = hashlib.sha256(content).hexdigest()
        version = _version(version_no=3, sha256=sha, storage_key=f"ui/art_a1/{sha}.js")
        calls = []
        with patch.object(ctrl.ui_service, "get_artifact", return_value=_artifact()), \
             patch.object(ctrl, "_write_bundle", side_effect=lambda *a: calls.append("write")), \
             patch.object(ctrl.ui_service, "publish", side_effect=lambda *a, **k: calls.append("publish") or version):
            result = await ctrl.publish(
                _request(), _upload(content), "art_a1", sha,
                label="Finance", icon="chart", min_host_version=1,
                source_digest="src", activate=True,
            )
        self.assertEqual(calls, ["write", "publish"])
        self.assertEqual(result["version_no"], 3)
        self.assertNotIn("id", result)

    async def test_failed_bundle_write_inserts_no_version_and_moves_no_pointer(self):
        content = b"export default 42;"
        sha = hashlib.sha256(content).hexdigest()
        with patch.object(ctrl.ui_service, "get_artifact", return_value=_artifact()), \
             patch.object(ctrl, "_write_bundle", side_effect=RuntimeError("s3 down")), \
             patch.object(ctrl.ui_service, "publish") as pub_fn:
            with self.assertRaises(RuntimeError):
                await ctrl.publish(_request(), _upload(content), "art_a1", sha)
        pub_fn.assert_not_called()

    async def test_publish_unknown_artifact_is_404_and_writes_nothing(self):
        content = b"x"
        sha = hashlib.sha256(content).hexdigest()
        with patch.object(ctrl.ui_service, "get_artifact", return_value=None), \
             patch.object(ctrl, "_write_bundle") as write_fn, \
             patch.object(ctrl.ui_service, "publish") as pub_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.publish(_request(), _upload(content), "nope99", sha)
        self.assertEqual(ctx.exception.status_code, 404)
        write_fn.assert_not_called()
        pub_fn.assert_not_called()

    async def test_publish_with_description_returns_it_in_response_body(self):
        content = b"export default 42;"
        sha = hashlib.sha256(content).hexdigest()
        version = _version(version_no=3, sha256=sha, storage_key=f"ui/art_a1/{sha}.js", description="[2991] fix overflow")
        with patch.object(ctrl.ui_service, "get_artifact", return_value=_artifact()), \
             patch.object(ctrl, "_write_bundle"), \
             patch.object(ctrl.ui_service, "publish", return_value=version) as pub_fn:
            result = await ctrl.publish(
                _request(), _upload(content), "art_a1", sha, description="[2991] fix overflow",
            )
        self.assertEqual(result["description"], "[2991] fix overflow")
        self.assertEqual(pub_fn.call_args.kwargs["description"], "[2991] fix overflow")

    async def test_publish_without_description_returns_none(self):
        content = b"export default 42;"
        sha = hashlib.sha256(content).hexdigest()
        version = _version(version_no=3, sha256=sha, storage_key=f"ui/art_a1/{sha}.js")
        with patch.object(ctrl.ui_service, "get_artifact", return_value=_artifact()), \
             patch.object(ctrl, "_write_bundle"), \
             patch.object(ctrl.ui_service, "publish", return_value=version) as pub_fn:
            result = await ctrl.publish(_request(), _upload(content), "art_a1", sha, description=None)
        self.assertIsNone(result["description"])
        self.assertIsNone(pub_fn.call_args.kwargs["description"])

    async def test_description_over_200_chars_is_400_and_inserts_no_version(self):
        content = b"export default 42;"
        sha = hashlib.sha256(content).hexdigest()
        too_long = "x" * 201
        with patch.object(ctrl.ui_service, "get_artifact", return_value=_artifact()), \
             patch.object(ctrl, "_write_bundle") as write_fn, \
             patch.object(ctrl.ui_service, "publish") as pub_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.publish(_request(), _upload(content), "art_a1", sha, description=too_long)
        self.assertEqual(ctx.exception.status_code, 400)
        write_fn.assert_not_called()
        pub_fn.assert_not_called()


class LocalFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_local_storage_round_trip(self):
        content = b"export default 'local';"
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(ctrl, "S3_BUCKET", ""), \
             patch.dict("os.environ", {"Y_AGENT_UI_BUNDLE_DIR": tmp}):
            key = "ui/art_a1/deadbeef.js"
            ctrl._write_bundle(key, content)
            self.assertEqual(ctrl._read_bundle(key), content)
            with self.assertRaises(HTTPException) as ctx:
                ctrl._read_bundle("ui/art_a1/missing.js")
            self.assertEqual(ctx.exception.status_code, 404)

    async def test_local_write_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(ctrl, "S3_BUCKET", ""), \
             patch.dict("os.environ", {"Y_AGENT_UI_BUNDLE_DIR": tmp}):
            with self.assertRaises(HTTPException) as ctx:
                ctrl._write_bundle("ui/../../evil.js", b"x")
            self.assertEqual(ctx.exception.status_code, 400)


class BundleTest(unittest.IsolatedAsyncioTestCase):
    async def test_bundle_serves_javascript_with_immutable_cache_control(self):
        with patch.object(ctrl.ui_service, "get_version", return_value=_version()) as get_fn, \
             patch.object(ctrl, "_read_bundle", return_value=b"js bytes") as read_fn:
            resp = await ctrl.get_bundle("ver_a1", _request())
        get_fn.assert_called_once_with(123, "ver_a1")
        read_fn.assert_called_once_with("ui/art_a1/aaa.js")
        self.assertEqual(resp.body, b"js bytes")
        self.assertEqual(resp.media_type, "text/javascript")
        self.assertEqual(resp.headers["Cache-Control"], "public, max-age=31536000, immutable")

    async def test_bundle_for_another_users_version_is_404(self):
        with patch.object(ctrl.ui_service, "get_version", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.get_bundle("ver_other", _request(user_id=456))
        self.assertEqual(ctx.exception.status_code, 404)


class PointerActionTest(unittest.IsolatedAsyncioTestCase):
    async def test_rollback_by_artifact_id(self):
        with patch.object(ctrl.ui_service, "get_artifact", return_value=_artifact()), \
             patch.object(ctrl.ui_service, "rollback", return_value=_artifact(active_version_id="ver_a0")) as rb:
            result = await ctrl.rollback(ctrl.RollbackRequest(artifact_id="art_a1"), _request())
        rb.assert_called_once_with(123, "art_a1", from_version_id=None)
        self.assertEqual(result["active_version_id"], "ver_a0")

    async def test_rollback_by_slug(self):
        with patch.object(ctrl.ui_service, "get_artifact_by_slug", return_value=_artifact()) as by_slug, \
             patch.object(ctrl.ui_service, "rollback", return_value=_artifact(active_version_id="ver_a0")) as rb:
            result = await ctrl.rollback(ctrl.RollbackRequest(slug="finance"), _request())
        by_slug.assert_called_once_with(123, "finance")
        rb.assert_called_once_with(123, "art_a1", from_version_id=None)
        self.assertEqual(result["active_version_id"], "ver_a0")

    async def test_rollback_passes_from_version_id_through(self):
        with patch.object(ctrl.ui_service, "get_artifact", return_value=_artifact()), \
             patch.object(ctrl.ui_service, "rollback", return_value=_artifact(active_version_id="ver_a0")) as rb:
            await ctrl.rollback(
                ctrl.RollbackRequest(artifact_id="art_a1", from_version_id="ver_a1"), _request()
            )
        rb.assert_called_once_with(123, "art_a1", from_version_id="ver_a1")

    async def test_rollback_conflict_when_active_pointer_has_moved_is_409(self):
        from storage.service.ui_artifact import RollbackConflictError

        with patch.object(ctrl.ui_service, "get_artifact", return_value=_artifact()), \
             patch.object(
                 ctrl.ui_service, "rollback", side_effect=RollbackConflictError("ver_a2")
             ):
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.rollback(
                    ctrl.RollbackRequest(artifact_id="art_a1", from_version_id="ver_a1"), _request()
                )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["active_version_id"], "ver_a2")

    async def test_action_requires_artifact_id_or_slug(self):
        with self.assertRaises(HTTPException) as ctx:
            await ctrl.rollback(ctrl.RollbackRequest(), _request())
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_action_unknown_artifact_is_404(self):
        with patch.object(ctrl.ui_service, "get_artifact_by_slug", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.rollback(ctrl.RollbackRequest(slug="nope"), _request())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_rollback_nothing_to_roll_back_is_404(self):
        with patch.object(ctrl.ui_service, "get_artifact", return_value=_artifact()), \
             patch.object(ctrl.ui_service, "rollback", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.rollback(ctrl.RollbackRequest(artifact_id="art_a1"), _request())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_activate_by_slug(self):
        with patch.object(ctrl.ui_service, "get_artifact_by_slug", return_value=_artifact()), \
             patch.object(ctrl.ui_service, "activate", return_value=_artifact(active_version_id="ver_a0")) as act:
            result = await ctrl.activate(ctrl.ActivateRequest(slug="finance", version_no=1), _request())
        act.assert_called_once_with(123, "art_a1", 1)
        self.assertEqual(result["active_version_id"], "ver_a0")

    async def test_enable_toggle_by_slug(self):
        with patch.object(ctrl.ui_service, "get_artifact_by_slug", return_value=_artifact()), \
             patch.object(ctrl.ui_service, "set_enabled", return_value=_artifact(enabled=False)) as se:
            result = await ctrl.set_enabled(ctrl.EnableRequest(slug="finance", enabled=False), _request())
        se.assert_called_once_with(123, "art_a1", False)
        self.assertFalse(result["enabled"])

    async def test_versions_unknown_artifact_is_404(self):
        with patch.object(ctrl.ui_service, "get_artifact", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.list_versions(_request(), artifact_id="nope99")
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_versions_by_slug(self):
        with patch.object(ctrl.ui_service, "get_artifact_by_slug", return_value=_artifact()) as by_slug, \
             patch.object(ctrl.ui_service, "list_versions", return_value=[_version()]) as lv:
            result = await ctrl.list_versions(_request(), artifact_id=None, slug="finance")
        by_slug.assert_called_once_with(123, "finance")
        lv.assert_called_once_with(123, "art_a1")
        self.assertEqual(result[0]["version_id"], "ver_a1")

    async def test_versions_requires_artifact_id_or_slug(self):
        with self.assertRaises(HTTPException) as ctx:
            await ctrl.list_versions(_request(), artifact_id=None, slug=None)
        self.assertEqual(ctx.exception.status_code, 400)


class DeleteTest(unittest.IsolatedAsyncioTestCase):
    async def test_delete_by_slug_deletes_rows_then_bundles_in_order(self):
        calls = []
        with patch.object(ctrl.ui_service, "get_artifact_by_slug", return_value=_artifact()) as by_slug, \
             patch.object(
                 ctrl.ui_service, "delete_artifact",
                 side_effect=lambda *a, **k: calls.append("delete_rows") or ["ui/art_a1/aaa.js", "ui/art_a1/bbb.js"],
             ) as del_fn, \
             patch.object(ctrl, "_delete_bundle", side_effect=lambda key: calls.append(f"delete_bundle:{key}")):
            result = await ctrl.delete_artifact(ctrl.DeleteRequest(slug="finance"), _request())
        by_slug.assert_called_once_with(123, "finance")
        del_fn.assert_called_once_with(123, "art_a1")
        self.assertEqual(
            calls,
            ["delete_rows", "delete_bundle:ui/art_a1/aaa.js", "delete_bundle:ui/art_a1/bbb.js"],
        )
        self.assertEqual(result, {"artifact_id": "art_a1", "slug": "finance", "deleted_versions": 2})

    async def test_delete_by_artifact_id(self):
        with patch.object(ctrl.ui_service, "get_artifact", return_value=_artifact()), \
             patch.object(ctrl.ui_service, "delete_artifact", return_value=[]) as del_fn, \
             patch.object(ctrl, "_delete_bundle") as bundle_fn:
            result = await ctrl.delete_artifact(ctrl.DeleteRequest(artifact_id="art_a1"), _request())
        del_fn.assert_called_once_with(123, "art_a1")
        bundle_fn.assert_not_called()
        self.assertEqual(result["deleted_versions"], 0)

    async def test_delete_requires_artifact_id_or_slug(self):
        with self.assertRaises(HTTPException) as ctx:
            await ctrl.delete_artifact(ctrl.DeleteRequest(), _request())
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_delete_unknown_artifact_is_404(self):
        with patch.object(ctrl.ui_service, "get_artifact_by_slug", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.delete_artifact(ctrl.DeleteRequest(slug="nope"), _request())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_delete_bundle_local_round_trip_and_missing_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(ctrl, "S3_BUCKET", ""), \
             patch.dict("os.environ", {"Y_AGENT_UI_BUNDLE_DIR": tmp}):
            key = "ui/art_a1/deadbeef.js"
            ctrl._write_bundle(key, b"x")
            ctrl._delete_bundle(key)
            with self.assertRaises(HTTPException):
                ctrl._read_bundle(key)
            # Deleting an already-missing bundle must not raise.
            ctrl._delete_bundle(key)

    async def test_delete_bundle_rejects_path_escape_silently(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(ctrl, "S3_BUCKET", ""), \
             patch.dict("os.environ", {"Y_AGENT_UI_BUNDLE_DIR": tmp}):
            # No exception: best-effort cleanup never raises back to the caller.
            ctrl._delete_bundle("ui/../../evil.js")


if __name__ == "__main__":
    unittest.main()
