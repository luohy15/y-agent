"""Unit tests for api.controller.module (todo 2412 origin, renamed under todo 3020 phase 1).

storage.service.module and the bundle I/O helpers are mocked; nothing
touches a real database or S3.
"""

import hashlib
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import storage.database.base as dbbase
import storage.entity.user  # noqa: F401 - registers UserEntity with Base.metadata
from api.controller import module as ctrl
from api.module_runtime import loader as module_loader
from api.module_runtime.preflight import SchemaPreflightError, check_metadata_against_database
from storage.dto.module import Module
from storage.dto.module_version import ModuleVersion
from storage.repository.user import get_or_create_user
from storage.service.module import DeleteResult


def _request(user_id=123):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id))


def _module(**overrides):
    base = dict(module_id="mod_a1", slug="finance")
    base.update(overrides)
    return Module(**base)


def _version(**overrides):
    base = dict(
        version_id="ver_a1",
        module_id="mod_a1",
        version_no=1,
        ui_sha256="aaa",
        ui_storage_key="module/mod_a1/aaa.js",
    )
    base.update(overrides)
    return ModuleVersion(**base)


def _upload(content: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename="bundle.js")


class CreateTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_returns_module_without_integer_ids(self):
        with patch.object(ctrl.module_service, "create_module", return_value=_module()) as create_fn:
            result = await ctrl.create_module(ctrl.CreateRequest(slug="finance"), _request())
        create_fn.assert_called_once_with(123, "finance")
        self.assertEqual(result["module_id"], "mod_a1")
        self.assertNotIn("id", result)
        self.assertNotIn("user_id", result)

    async def test_create_rejects_invalid_slug(self):
        for bad in ["", "Finance", "-lead", "has space", "under_score", "../x", "a" * 64]:
            with patch.object(ctrl.module_service, "create_module") as create_fn:
                with self.assertRaises(HTTPException) as ctx:
                    await ctrl.create_module(ctrl.CreateRequest(slug=bad), _request())
            self.assertEqual(ctx.exception.status_code, 400, bad)
            create_fn.assert_not_called()

    async def test_create_rejects_reserved_slug(self):
        for reserved in ("list", "publish", "bundle", "schema-sql"):
            with patch.object(ctrl.module_service, "create_module") as create_fn:
                with self.assertRaises(HTTPException) as ctx:
                    await ctrl.create_module(ctrl.CreateRequest(slug=reserved), _request())
            self.assertEqual(ctx.exception.status_code, 400, reserved)
            create_fn.assert_not_called()


class ListTest(unittest.IsolatedAsyncioTestCase):
    async def test_maintainer_list_joins_active_version_and_omits_integer_ids(self):
        module = _module(active_version_id="ver_a1")
        version = _version()
        with patch.object(ctrl, "default_owner_user_id", return_value=123), \
             patch.object(ctrl.module_service, "list_modules", return_value=[module]), \
             patch.object(ctrl.module_service, "get_version", return_value=version):
            result = await ctrl.list_modules(_request(), enabled_only=False)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["active_version"]["version_id"], "ver_a1")
        self.assertNotIn("id", result[0])
        self.assertNotIn("user_id", result[0])
        self.assertNotIn("id", result[0]["active_version"])

    async def test_maintainer_list_no_active_version_returns_null(self):
        with patch.object(ctrl, "default_owner_user_id", return_value=123), \
             patch.object(ctrl.module_service, "list_modules", return_value=[_module()]), \
             patch.object(ctrl.module_service, "get_version") as get_fn:
            result = await ctrl.list_modules(_request())
        get_fn.assert_not_called()
        self.assertIsNone(result[0]["active_version"])

    async def test_non_maintainer_list_only_includes_authenticated_scoped_versions(self):
        finance = _module(module_id="finance", slug="finance", active_version_id="vf")
        chat = _module(module_id="chat", slug="chat", active_version_id="vc")
        versions = {
            "vf": _version(version_id="vf", module_id="finance"),
            "vc": _version(
                version_id="vc",
                module_id="chat",
                dispatch_scope="authenticated",
                ui_sha256="chat-ui-sha",
                ui_storage_key="module/chat/chat-ui-sha.js",
                api_sha256="chat-api-sha",
                api_storage_key="module/chat/chat-api-sha.api.zip",
                source_digest="chat-src",
                label="Chat",
                icon="message",
                min_host_version=2,
                description="private build note",
            ),
        }
        with patch.object(ctrl, "default_owner_user_id", return_value=123), \
             patch.object(ctrl.module_service, "list_modules", return_value=[finance, chat]) as list_fn, \
             patch.object(
                 ctrl.module_service, "get_version", side_effect=lambda owner, version_id: versions[version_id]
             ):
            result = await ctrl.list_modules(_request(user_id=456), enabled_only=False)
        list_fn.assert_called_once_with(123, enabled_only=True)
        self.assertEqual([row["slug"] for row in result], ["chat"])
        # S5: non-maintainer projection is browser-loader fields only.
        active = result[0]["active_version"]
        self.assertEqual(
            active,
            {
                "version_id": "vc",
                "version_no": 1,
                "ui_sha256": "chat-ui-sha",
                "min_host_version": 2,
                "label": "Chat",
                "icon": "message",
            },
        )
        for secret in (
            "ui_storage_key",
            "api_storage_key",
            "api_sha256",
            "source_digest",
            "description",
            "dispatch_scope",
        ):
            self.assertNotIn(secret, active)

    async def test_maintainer_list_keeps_full_active_version_dict(self):
        module = _module(active_version_id="ver_a1")
        version = _version(
            ui_storage_key="module/mod_a1/aaa.js",
            api_sha256="api-sha",
            api_storage_key="module/mod_a1/api-sha.api.zip",
            source_digest="src-digest",
            dispatch_scope="maintainer",
        )
        with patch.object(ctrl, "default_owner_user_id", return_value=123), \
             patch.object(ctrl.module_service, "list_modules", return_value=[module]), \
             patch.object(ctrl.module_service, "get_version", return_value=version):
            result = await ctrl.list_modules(_request(), enabled_only=False)
        active = result[0]["active_version"]
        self.assertEqual(active["ui_storage_key"], "module/mod_a1/aaa.js")
        self.assertEqual(active["api_sha256"], "api-sha")
        self.assertEqual(active["api_storage_key"], "module/mod_a1/api-sha.api.zip")
        self.assertEqual(active["source_digest"], "src-digest")
        self.assertEqual(active["dispatch_scope"], "maintainer")

    async def test_list_fails_closed_when_maintainer_is_unset(self):
        with patch.object(ctrl, "default_owner_user_id", return_value=None), \
             patch.object(ctrl.module_service, "list_modules") as list_fn:
            result = await ctrl.list_modules(_request(user_id=456))
        self.assertEqual(result, [])
        list_fn.assert_not_called()


class PublishTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Publish is restricted to the trusted maintainer; bind it to the test user.
        self._owner_patch = patch.object(ctrl, "default_owner_user_id", return_value=123)
        self._owner_patch.start()

    def tearDown(self):
        self._owner_patch.stop()

    async def test_publish_restricted_to_maintainer_forbids_other_accounts(self):
        """review finding 1: an authenticated non-owner cannot publish a backend half."""
        content = b"PK\x03\x04api-archive"
        sha = hashlib.sha256(content).hexdigest()
        with patch.object(ctrl, "default_owner_user_id", return_value=999), \
             patch.object(ctrl.module_service, "get_module") as get_fn, \
             patch.object(ctrl, "_write_bundle") as write_fn, \
             patch.object(ctrl.module_service, "publish") as pub_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.publish(
                    _request(), api_file=_upload(content), module_id="mod_a1", api_sha256=sha
                )
        self.assertEqual(ctx.exception.status_code, 403)
        get_fn.assert_not_called()
        write_fn.assert_not_called()
        pub_fn.assert_not_called()

    async def test_publish_rejects_invalid_dispatch_scope(self):
        content = b"export default () => null;"
        sha = hashlib.sha256(content).hexdigest()
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl, "_write_bundle") as write_fn, \
             patch.object(ctrl.module_service, "publish") as pub_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.publish(
                    _request(), file=_upload(content), module_id="mod_a1", sha256=sha,
                    dispatch_scope="public",
                )
        self.assertEqual(ctx.exception.status_code, 400)
        write_fn.assert_not_called()
        pub_fn.assert_not_called()

    async def test_hash_mismatch_is_rejected(self):
        content = b"export default () => null;"
        bad_hash = "0" * 64
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl.module_service, "publish") as pub_fn, \
             patch.object(ctrl, "_write_bundle") as write_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.publish(
                    _request(), file=_upload(content), module_id="mod_a1", sha256=bad_hash
                )
        self.assertEqual(ctx.exception.status_code, 400)
        pub_fn.assert_not_called()
        write_fn.assert_not_called()

    async def test_hash_compare_is_case_insensitive(self):
        content = b"export default 42;"
        sha = hashlib.sha256(content).hexdigest().upper()
        version = _version(version_no=3, ui_sha256=sha.lower(), ui_storage_key=f"module/mod_a1/{sha.lower()}.js")
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl.module_service, "publish", return_value=version), \
             patch.object(ctrl, "_write_bundle"):
            result = await ctrl.publish(
                _request(), file=_upload(content), module_id="mod_a1", sha256=sha
            )
        self.assertEqual(result["version_no"], 3)

    async def test_publish_writes_bundle_before_inserting_version(self):
        content = b"export default 42;"
        sha = hashlib.sha256(content).hexdigest()
        version = _version(version_no=3, ui_sha256=sha, ui_storage_key=f"module/mod_a1/{sha}.js")
        calls = []
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl, "_write_bundle", side_effect=lambda *a, **k: calls.append("write")), \
             patch.object(ctrl.module_service, "publish", side_effect=lambda *a, **k: calls.append("publish") or version):
            result = await ctrl.publish(
                _request(), file=_upload(content), module_id="mod_a1", sha256=sha,
                label="Finance", icon="chart", min_host_version=1,
                source_digest="src", activate=True,
            )
        self.assertEqual(calls, ["write", "publish"])
        self.assertEqual(result["version_no"], 3)
        self.assertNotIn("id", result)

    async def test_failed_bundle_write_inserts_no_version_and_moves_no_pointer(self):
        content = b"export default 42;"
        sha = hashlib.sha256(content).hexdigest()
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl, "_write_bundle", side_effect=RuntimeError("s3 down")), \
             patch.object(ctrl.module_service, "publish") as pub_fn:
            with self.assertRaises(RuntimeError):
                await ctrl.publish(
                    _request(), file=_upload(content), module_id="mod_a1", sha256=sha
                )
        pub_fn.assert_not_called()

    async def test_publish_unknown_module_is_404_and_writes_nothing(self):
        content = b"x"
        sha = hashlib.sha256(content).hexdigest()
        with patch.object(ctrl.module_service, "get_module", return_value=None), \
             patch.object(ctrl, "_write_bundle") as write_fn, \
             patch.object(ctrl.module_service, "publish") as pub_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.publish(
                    _request(), file=_upload(content), module_id="nope99", sha256=sha
                )
        self.assertEqual(ctx.exception.status_code, 404)
        write_fn.assert_not_called()
        pub_fn.assert_not_called()

    async def test_publish_rejects_reserved_slug_before_writing_bundle(self):
        content = b"export default 42;"
        sha = hashlib.sha256(content).hexdigest()
        with patch.object(ctrl.module_service, "get_module", return_value=_module(slug="publish")), \
             patch.object(ctrl, "_write_bundle") as write_fn, \
             patch.object(ctrl.module_service, "publish") as pub_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.publish(
                    _request(), file=_upload(content), module_id="mod_a1", sha256=sha
                )
        self.assertEqual(ctx.exception.status_code, 400)
        write_fn.assert_not_called()
        pub_fn.assert_not_called()

    async def test_publish_with_description_returns_it_in_response_body(self):
        content = b"export default 42;"
        sha = hashlib.sha256(content).hexdigest()
        version = _version(version_no=3, ui_sha256=sha, ui_storage_key=f"module/mod_a1/{sha}.js", description="[2991] fix overflow")
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl, "_write_bundle"), \
             patch.object(ctrl.module_service, "publish", return_value=version) as pub_fn:
            result = await ctrl.publish(
                _request(), file=_upload(content), module_id="mod_a1", sha256=sha,
                description="[2991] fix overflow",
            )
        self.assertEqual(result["description"], "[2991] fix overflow")
        self.assertEqual(pub_fn.call_args.kwargs["description"], "[2991] fix overflow")

    async def test_publish_without_description_returns_none(self):
        content = b"export default 42;"
        sha = hashlib.sha256(content).hexdigest()
        version = _version(version_no=3, ui_sha256=sha, ui_storage_key=f"module/mod_a1/{sha}.js")
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl, "_write_bundle"), \
             patch.object(ctrl.module_service, "publish", return_value=version) as pub_fn:
            result = await ctrl.publish(
                _request(), file=_upload(content), module_id="mod_a1", sha256=sha, description=None
            )
        self.assertIsNone(result["description"])
        self.assertIsNone(pub_fn.call_args.kwargs["description"])

    async def test_description_over_200_chars_is_400_and_inserts_no_version(self):
        content = b"export default 42;"
        sha = hashlib.sha256(content).hexdigest()
        too_long = "x" * 201
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl, "_write_bundle") as write_fn, \
             patch.object(ctrl.module_service, "publish") as pub_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.publish(
                    _request(), file=_upload(content), module_id="mod_a1", sha256=sha,
                    description=too_long,
                )
        self.assertEqual(ctx.exception.status_code, 400)
        write_fn.assert_not_called()
        pub_fn.assert_not_called()

    async def test_publish_both_halves_writes_two_keys_and_one_version_row(self):
        ui = b"export default 42;"
        api = b"PK\x03\x04api-bytes"
        ui_sha = hashlib.sha256(ui).hexdigest()
        api_sha = hashlib.sha256(api).hexdigest()
        version = _version(
            version_no=4,
            ui_sha256=ui_sha,
            ui_storage_key=f"module/mod_a1/{ui_sha}.js",
            api_sha256=api_sha,
            api_storage_key=f"module/mod_a1/{api_sha}.api.zip",
        )
        writes = []
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(
                 ctrl, "import_candidate_for_preflight",
                 return_value=("ymod_finance_x", object(), None),
             ) as preflight_fn, \
             patch.object(
                 ctrl, "_write_bundle",
                 side_effect=lambda key, content, **k: writes.append((key, content, k.get("content_type"))),
             ), \
             patch.object(ctrl.module_service, "publish", return_value=version) as pub_fn:
            result = await ctrl.publish(
                _request(),
                file=_upload(ui),
                module_id="mod_a1",
                sha256=ui_sha,
                api_file=_upload(api),
                api_sha256=api_sha,
                min_backend_version=1,
            )
        preflight_fn.assert_called_once_with("finance", api, 1)
        self.assertEqual(result["version_no"], 4)
        self.assertEqual(len(writes), 2)
        self.assertEqual(writes[0][0], f"module/mod_a1/{ui_sha}.js")
        self.assertEqual(writes[1][0], f"module/mod_a1/{api_sha}.api.zip")
        self.assertEqual(writes[1][2], "application/zip")
        kwargs = pub_fn.call_args.kwargs
        self.assertEqual(kwargs["ui_sha256"], ui_sha)
        self.assertEqual(kwargs["api_sha256"], api_sha)
        self.assertEqual(kwargs["min_backend_version"], 1)
        # Exactly one publish call = one version row spanning both halves.
        self.assertEqual(pub_fn.call_count, 1)

    async def test_publish_api_only_half_is_allowed(self):
        api = b"PK\x03\x04api-only"
        api_sha = hashlib.sha256(api).hexdigest()
        version = _version(
            version_no=1,
            ui_sha256=None,
            ui_storage_key=None,
            api_sha256=api_sha,
            api_storage_key=f"module/mod_a1/{api_sha}.api.zip",
        )
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(
                 ctrl, "import_candidate_for_preflight",
                 return_value=("ymod_finance_x", object(), None),
             ), \
             patch.object(ctrl, "_write_bundle") as write_fn, \
             patch.object(ctrl.module_service, "publish", return_value=version) as pub_fn:
            result = await ctrl.publish(
                _request(),
                file=None,
                module_id="mod_a1",
                api_file=_upload(api),
                api_sha256=api_sha,
            )
        self.assertEqual(result["api_sha256"], api_sha)
        self.assertIsNone(result["ui_sha256"])
        write_fn.assert_called_once()
        self.assertEqual(pub_fn.call_args.kwargs["api_sha256"], api_sha)
        self.assertIsNone(pub_fn.call_args.kwargs["ui_sha256"])

    async def test_publish_rejects_oversized_upload(self):
        """review finding 3: the publish endpoint must not buffer unbounded bytes."""
        content = b"x" * (ctrl.MAX_UPLOAD_BYTES + 1)
        sha = hashlib.sha256(content).hexdigest()
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl, "_write_bundle") as write_fn, \
             patch.object(ctrl.module_service, "publish") as pub_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.publish(
                    _request(), file=_upload(content), module_id="mod_a1", sha256=sha
                )
        self.assertEqual(ctx.exception.status_code, 400)
        write_fn.assert_not_called()
        pub_fn.assert_not_called()

    async def test_publish_requires_at_least_one_half(self):
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl, "_write_bundle") as write_fn, \
             patch.object(ctrl.module_service, "publish") as pub_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.publish(_request(), file=None, module_id="mod_a1")
        self.assertEqual(ctx.exception.status_code, 400)
        write_fn.assert_not_called()
        pub_fn.assert_not_called()


def _module_zip_with_table(table_name: str, extra_column_sql: str = "") -> bytes:
    """A minimal API-half zip: a trivial router plus one entity declared
    against its own DeclarativeBase (plan D11), so `<pkg>.entities.metadata`
    is non-empty and the publish-time preflight (D7) has something to check."""
    files = {
        "__init__.py": "# empty\n",
        "api.py": "from fastapi import APIRouter\nrouter = APIRouter()\n",
        "entities/__init__.py": (
            "from .base import Base\n"
            "from . import widget  # noqa: F401\n"
            "metadata = Base.metadata\n"
        ),
        "entities/base.py": (
            "from sqlalchemy.orm import DeclarativeBase\n\n\n"
            "class Base(DeclarativeBase):\n"
            "    pass\n"
        ),
        "entities/widget.py": (
            "from sqlalchemy import Column, Integer, String\n"
            "from .base import Base\n\n\n"
            "class Widget(Base):\n"
            f"    __tablename__ = {table_name!r}\n"
            "    id = Column(Integer, primary_key=True)\n"
            "    name = Column(String)\n"
            f"{extra_column_sql}"
        ),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in sorted(files.items()):
            zf.writestr(name, content)
    return buf.getvalue()


class SchemaPreflightTest(unittest.IsolatedAsyncioTestCase):
    """Plan 4.3: the publish handler preflights a module's declared entities
    against information_schema before writing bundles or inserting a version.
    """

    def setUp(self):
        self._owner_patch = patch.object(ctrl, "default_owner_user_id", return_value=123)
        self._owner_patch.start()
        self._tmpdir = tempfile.TemporaryDirectory()
        self._extract_patch = patch.object(module_loader, "EXTRACT_ROOT", Path(self._tmpdir.name))
        self._extract_patch.start()

    def tearDown(self):
        self._owner_patch.stop()
        self._extract_patch.stop()
        for key in list(sys.modules):
            if key.startswith("ymod_"):
                sys.modules.pop(key, None)
        self._tmpdir.cleanup()

    def _sqlite_engine(self):
        return create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

    async def test_publish_rejects_backend_contract_skew_before_writes(self):
        api_bytes = _module_zip_with_no_entities()
        api_sha = hashlib.sha256(api_bytes).hexdigest()
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl, "_write_bundle") as write_fn, \
             patch.object(ctrl.module_service, "publish") as pub_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.publish(
                    _request(),
                    api_file=_upload(api_bytes),
                    module_id="mod_a1",
                    api_sha256=api_sha,
                    min_backend_version=99,
                )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["kind"], "backend_version")
        write_fn.assert_not_called()
        pub_fn.assert_not_called()

    async def test_publish_refused_when_declared_table_is_missing(self):
        api_bytes = _module_zip_with_table("widget_missing")
        api_sha = hashlib.sha256(api_bytes).hexdigest()
        module = _module(active_version_id="ver_prev")
        with patch.object(ctrl.module_service, "get_module", return_value=module), \
             patch.object(ctrl, "get_engine", return_value=self._sqlite_engine()), \
             patch.object(ctrl, "_write_bundle") as write_fn, \
             patch.object(ctrl.module_service, "publish") as pub_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.publish(
                    _request(), api_file=_upload(api_bytes), module_id="mod_a1", api_sha256=api_sha
                )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("widget_missing", ctx.exception.detail)
        write_fn.assert_not_called()
        pub_fn.assert_not_called()
        # The active pointer never moved: publish() was never called.
        self.assertEqual(module.active_version_id, "ver_prev")
        pkg_name = module_loader.package_name_for("finance", api_sha)
        self.assertFalse(any(key == pkg_name or key.startswith(pkg_name + ".") for key in sys.modules))

    async def test_publish_succeeds_after_table_is_created(self):
        api_bytes = _module_zip_with_table("widget_ok")
        api_sha = hashlib.sha256(api_bytes).hexdigest()
        engine = self._sqlite_engine()
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE widget_ok (id INTEGER PRIMARY KEY, name VARCHAR)"))
        version = _version(
            version_no=1,
            ui_sha256=None,
            ui_storage_key=None,
            api_sha256=api_sha,
            api_storage_key=f"module/mod_a1/{api_sha}.api.zip",
        )
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl, "get_engine", return_value=engine), \
             patch.object(ctrl, "_write_bundle") as write_fn, \
             patch.object(ctrl.module_service, "publish", return_value=version) as pub_fn:
            result = await ctrl.publish(
                _request(), api_file=_upload(api_bytes), module_id="mod_a1", api_sha256=api_sha
            )
        self.assertEqual(result["api_sha256"], api_sha)
        write_fn.assert_called_once()
        pub_fn.assert_called_once()

    async def test_extra_database_column_not_declared_by_model_is_not_an_error(self):
        api_bytes = _module_zip_with_table("widget_extra")
        api_sha = hashlib.sha256(api_bytes).hexdigest()
        engine = self._sqlite_engine()
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE widget_extra "
                    "(id INTEGER PRIMARY KEY, name VARCHAR, extra_col VARCHAR)"
                )
            )
        version = _version(
            version_no=1,
            ui_sha256=None,
            ui_storage_key=None,
            api_sha256=api_sha,
            api_storage_key=f"module/mod_a1/{api_sha}.api.zip",
        )
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl, "get_engine", return_value=engine), \
             patch.object(ctrl, "_write_bundle") as write_fn, \
             patch.object(ctrl.module_service, "publish", return_value=version) as pub_fn:
            result = await ctrl.publish(
                _request(), api_file=_upload(api_bytes), module_id="mod_a1", api_sha256=api_sha
            )
        self.assertEqual(result["api_sha256"], api_sha)
        write_fn.assert_called_once()

    async def test_module_with_no_entities_skips_preflight(self):
        api_bytes = _module_zip_with_no_entities()
        api_sha = hashlib.sha256(api_bytes).hexdigest()
        version = _version(
            version_no=1,
            ui_sha256=None,
            ui_storage_key=None,
            api_sha256=api_sha,
            api_storage_key=f"module/mod_a1/{api_sha}.api.zip",
        )
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl, "get_engine") as engine_fn, \
             patch.object(ctrl, "_write_bundle") as write_fn, \
             patch.object(ctrl.module_service, "publish", return_value=version) as pub_fn:
            result = await ctrl.publish(
                _request(), api_file=_upload(api_bytes), module_id="mod_a1", api_sha256=api_sha
            )
        self.assertEqual(result["api_sha256"], api_sha)
        write_fn.assert_called_once()
        pub_fn.assert_called_once()
        # No entities submodule -> no reason to touch the database at all.
        engine_fn.assert_not_called()


class SchemaQualifiedPreflightTest(unittest.TestCase):
    def test_uses_schema_qualified_identifiers_without_manual_quoting(self):
        from sqlalchemy import Column, Integer, MetaData, Table

        metadata = MetaData()
        Table("Widget", metadata, Column("Name", Integer), schema="Analytics")
        inspector = MagicMock()
        inspector.has_table.return_value = True
        inspector.get_columns.return_value = [{"name": "Name"}]
        with patch("api.module_runtime.preflight.sa_inspect", return_value=inspector):
            check_metadata_against_database("scratch", metadata, MagicMock())
        inspector.has_table.assert_called_once_with("Widget", schema="Analytics")
        inspector.get_columns.assert_called_once_with("Widget", schema="Analytics")

    def test_external_reference_tables_are_not_preflighted(self):
        """A module's stub for a host kernel table is skipped: it does not own it."""
        from sqlalchemy import Column, Integer, MetaData, Table

        from agent.module_host import EXTERNAL_TABLE_INFO_KEY

        metadata = MetaData()
        Table("user", metadata, Column("id", Integer), info={EXTERNAL_TABLE_INFO_KEY: True})
        Table("mod_thing", metadata, Column("id", Integer))
        inspector = MagicMock()
        inspector.has_table.return_value = True
        inspector.get_columns.return_value = [{"name": "id"}]
        with patch("api.module_runtime.preflight.sa_inspect", return_value=inspector):
            check_metadata_against_database("scratch", metadata, MagicMock())
        inspector.has_table.assert_called_once_with("mod_thing", schema=None)

    def test_reports_multiple_schema_qualified_tables_and_columns(self):
        from sqlalchemy import Column, Integer, MetaData, Table

        metadata = MetaData()
        Table("missing", metadata, Column("id", Integer), schema="analytics")
        Table("present", metadata, Column("id", Integer), Column("name", Integer), schema="audit")
        inspector = MagicMock()
        inspector.has_table.side_effect = [False, True]
        inspector.get_columns.return_value = [{"name": "id"}]
        with patch("api.module_runtime.preflight.sa_inspect", return_value=inspector):
            with self.assertRaises(SchemaPreflightError) as ctx:
                check_metadata_against_database("scratch", metadata, MagicMock())
        self.assertIn("analytics.missing", ctx.exception.report)
        self.assertIn("audit.present", ctx.exception.report)
        self.assertIn("name", ctx.exception.report)


def _module_zip_with_no_entities() -> bytes:
    files = {
        "__init__.py": "# empty\n",
        "api.py": "from fastapi import APIRouter\nrouter = APIRouter()\n",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in sorted(files.items()):
            zf.writestr(name, content)
    return buf.getvalue()


class DefaultOwnerResolverTest(unittest.IsolatedAsyncioTestCase):
    """Exercises the real default_owner_user_id() resolver end-to-end against
    an in-memory SQLite DB. The rest of this suite patches the resolver to
    isolate other publish behaviour; that patching previously hid a
    regression where the gate resolved to a synthetic "default" bootstrap
    account instead of the configured maintainer (review finding 1), so this
    class must never patch `ctrl.default_owner_user_id`.
    """

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
        self._orig_env = os.environ.pop("Y_AGENT_MODULE_MAINTAINER_USER_ID", None)

    def tearDown(self):
        dbbase._engine = self._orig_engine
        dbbase._SessionLocal = self._orig_session_local
        if self._orig_env is None:
            os.environ.pop("Y_AGENT_MODULE_MAINTAINER_USER_ID", None)
        else:
            os.environ["Y_AGENT_MODULE_MAINTAINER_USER_ID"] = self._orig_env

    async def test_resolves_configured_public_user_id_to_owning_account(self):
        maintainer = get_or_create_user("maintainer_at_example_dot_com")
        other = get_or_create_user("someone-else")
        os.environ["Y_AGENT_MODULE_MAINTAINER_USER_ID"] = maintainer.user_id

        resolved = ctrl.default_owner_user_id()

        self.assertEqual(resolved, maintainer.id)
        self.assertNotEqual(resolved, other.id)

    async def test_fails_closed_when_env_var_unset(self):
        self.assertIsNone(ctrl.default_owner_user_id())

    async def test_fails_closed_when_configured_user_id_does_not_resolve(self):
        os.environ["Y_AGENT_MODULE_MAINTAINER_USER_ID"] = "nobody-with-this-user-id"
        self.assertIsNone(ctrl.default_owner_user_id())

    async def test_publish_gate_admits_configured_maintainer_not_the_default_row(self):
        """The regression this closes: get_default_user_id() resolves (and can
        create) a synthetic 'default' row distinct from whichever account
        actually owns module rows; the gate must not conflate the two."""
        maintainer = get_or_create_user("maintainer_at_example_dot_com")
        default_row = get_or_create_user("default")
        self.assertNotEqual(maintainer.id, default_row.id)
        os.environ["Y_AGENT_MODULE_MAINTAINER_USER_ID"] = maintainer.user_id

        with self.assertRaises(HTTPException) as ctx:
            await ctrl.publish(_request(user_id=default_row.id), module_id="mod_a1")
        self.assertEqual(ctx.exception.status_code, 403)

        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl, "_write_bundle") as write_fn, \
             patch.object(ctrl.module_service, "publish") as pub_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.publish(_request(user_id=maintainer.id), module_id="mod_a1")
        # Passes the maintainer gate and fails later, on "at least one half
        # required" (400) rather than the ownership gate (403).
        self.assertEqual(ctx.exception.status_code, 400)
        write_fn.assert_not_called()
        pub_fn.assert_not_called()


class LocalFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_local_storage_round_trip(self):
        content = b"export default 'local';"
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(ctrl, "S3_BUCKET", ""), \
             patch.dict("os.environ", {"Y_AGENT_MODULE_BUNDLE_DIR": tmp}):
            key = "module/mod_a1/deadbeef.js"
            ctrl._write_bundle(key, content)
            self.assertEqual(ctrl._read_bundle(key), content)
            with self.assertRaises(HTTPException) as ctx:
                ctrl._read_bundle("module/mod_a1/missing.js")
            self.assertEqual(ctx.exception.status_code, 404)

    async def test_local_write_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(ctrl, "S3_BUCKET", ""), \
             patch.dict("os.environ", {"Y_AGENT_MODULE_BUNDLE_DIR": tmp}):
            with self.assertRaises(HTTPException) as ctx:
                ctrl._write_bundle("module/../../evil.js", b"x")
            self.assertEqual(ctx.exception.status_code, 400)


class BundleTest(unittest.IsolatedAsyncioTestCase):
    async def test_bundle_serves_javascript_with_immutable_cache_control(self):
        with patch.object(ctrl, "default_owner_user_id", return_value=123), \
             patch.object(ctrl.module_service, "get_version", return_value=_version()) as get_fn, \
             patch.object(ctrl, "_read_bundle", return_value=b"js bytes") as read_fn:
            resp = await ctrl.get_bundle("ver_a1", _request())
        get_fn.assert_called_once_with(123, "ver_a1")
        read_fn.assert_called_once_with("module/mod_a1/aaa.js")
        self.assertEqual(resp.body, b"js bytes")
        self.assertEqual(resp.media_type, "text/javascript")
        self.assertEqual(resp.headers["Cache-Control"], "public, max-age=31536000, immutable")

    async def test_authenticated_scoped_bundle_is_served_to_non_maintainer(self):
        version = _version(dispatch_scope="authenticated")
        with patch.object(ctrl, "default_owner_user_id", return_value=123), \
             patch.object(ctrl.module_service, "get_version", return_value=version) as get_fn, \
             patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl, "_read_bundle", return_value=b"js bytes"):
            resp = await ctrl.get_bundle("ver_a1", _request(user_id=456))
        get_fn.assert_called_once_with(123, "ver_a1")
        self.assertEqual(resp.body, b"js bytes")

    async def test_maintainer_scoped_bundle_is_404_for_non_maintainer(self):
        with patch.object(ctrl, "default_owner_user_id", return_value=123), \
             patch.object(ctrl.module_service, "get_version", return_value=_version()), \
             patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl, "_read_bundle") as read_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.get_bundle("ver_a1", _request(user_id=456))
        self.assertEqual(ctx.exception.status_code, 404)
        read_fn.assert_not_called()

    async def test_disabled_authenticated_scoped_bundle_is_404_for_non_maintainer(self):
        version = _version(dispatch_scope="authenticated")
        with patch.object(ctrl, "default_owner_user_id", return_value=123), \
             patch.object(ctrl.module_service, "get_version", return_value=version), \
             patch.object(ctrl.module_service, "get_module", return_value=_module(enabled=False)), \
             patch.object(ctrl, "_read_bundle") as read_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.get_bundle("ver_a1", _request(user_id=456))
        self.assertEqual(ctx.exception.status_code, 404)
        read_fn.assert_not_called()

    async def test_bundle_fails_closed_when_maintainer_unset(self):
        with patch.object(ctrl, "default_owner_user_id", return_value=None), \
             patch.object(ctrl.module_service, "get_version") as get_fn:
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.get_bundle("ver_a1", _request(user_id=456))
        self.assertEqual(ctx.exception.status_code, 404)
        get_fn.assert_not_called()

    async def test_bundle_for_unknown_version_is_404(self):
        with patch.object(ctrl, "default_owner_user_id", return_value=123), \
             patch.object(ctrl.module_service, "get_version", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.get_bundle("ver_other", _request(user_id=456))
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_bundle_with_no_ui_half_is_404(self):
        with patch.object(ctrl, "default_owner_user_id", return_value=123), \
             patch.object(ctrl.module_service, "get_version", return_value=_version(ui_storage_key=None)):
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.get_bundle("ver_a1", _request())
        self.assertEqual(ctx.exception.status_code, 404)


class PointerActionTest(unittest.IsolatedAsyncioTestCase):
    async def test_rollback_by_module_id(self):
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl.module_service, "rollback", return_value=_module(active_version_id="ver_a0")) as rb:
            result = await ctrl.rollback(ctrl.RollbackRequest(module_id="mod_a1"), _request())
        rb.assert_called_once_with(123, "mod_a1", from_version_id=None)
        self.assertEqual(result["active_version_id"], "ver_a0")

    async def test_rollback_by_slug(self):
        with patch.object(ctrl.module_service, "get_module_by_slug", return_value=_module()) as by_slug, \
             patch.object(ctrl.module_service, "rollback", return_value=_module(active_version_id="ver_a0")) as rb:
            result = await ctrl.rollback(ctrl.RollbackRequest(slug="finance"), _request())
        by_slug.assert_called_once_with(123, "finance")
        rb.assert_called_once_with(123, "mod_a1", from_version_id=None)
        self.assertEqual(result["active_version_id"], "ver_a0")

    async def test_rollback_passes_from_version_id_through(self):
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl.module_service, "rollback", return_value=_module(active_version_id="ver_a0")) as rb:
            await ctrl.rollback(
                ctrl.RollbackRequest(module_id="mod_a1", from_version_id="ver_a1"), _request()
            )
        rb.assert_called_once_with(123, "mod_a1", from_version_id="ver_a1")

    async def test_rollback_conflict_when_active_pointer_has_moved_is_409(self):
        from storage.service.module import RollbackConflictError

        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(
                 ctrl.module_service, "rollback", side_effect=RollbackConflictError("ver_a2")
             ):
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.rollback(
                    ctrl.RollbackRequest(module_id="mod_a1", from_version_id="ver_a1"), _request()
                )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["active_version_id"], "ver_a2")

    async def test_action_requires_module_id_or_slug(self):
        with self.assertRaises(HTTPException) as ctx:
            await ctrl.rollback(ctrl.RollbackRequest(), _request())
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_action_unknown_module_is_404(self):
        with patch.object(ctrl.module_service, "get_module_by_slug", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.rollback(ctrl.RollbackRequest(slug="nope"), _request())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_rollback_nothing_to_roll_back_is_404(self):
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl.module_service, "rollback", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.rollback(ctrl.RollbackRequest(module_id="mod_a1"), _request())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_activate_by_slug(self):
        with patch.object(ctrl.module_service, "get_module_by_slug", return_value=_module()), \
             patch.object(ctrl.module_service, "activate", return_value=_module(active_version_id="ver_a0")) as act:
            result = await ctrl.activate(ctrl.ActivateRequest(slug="finance", version_no=1), _request())
        act.assert_called_once_with(123, "mod_a1", 1)
        self.assertEqual(result["active_version_id"], "ver_a0")

    async def test_enable_toggle_by_slug(self):
        with patch.object(ctrl.module_service, "get_module_by_slug", return_value=_module()), \
             patch.object(ctrl.module_service, "set_enabled", return_value=_module(enabled=False)) as se:
            result = await ctrl.set_enabled(ctrl.EnableRequest(slug="finance", enabled=False), _request())
        se.assert_called_once_with(123, "mod_a1", False)
        self.assertFalse(result["enabled"])

    async def test_versions_unknown_module_is_404(self):
        with patch.object(ctrl.module_service, "get_module", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.list_versions(_request(), module_id="nope99")
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_versions_by_slug(self):
        with patch.object(ctrl.module_service, "get_module_by_slug", return_value=_module()) as by_slug, \
             patch.object(ctrl.module_service, "list_versions", return_value=[_version()]) as lv:
            result = await ctrl.list_versions(_request(), module_id=None, slug="finance")
        by_slug.assert_called_once_with(123, "finance")
        lv.assert_called_once_with(123, "mod_a1")
        self.assertEqual(result[0]["version_id"], "ver_a1")

    async def test_versions_requires_module_id_or_slug(self):
        with self.assertRaises(HTTPException) as ctx:
            await ctrl.list_versions(_request(), module_id=None, slug=None)
        self.assertEqual(ctx.exception.status_code, 400)


class DeleteTest(unittest.IsolatedAsyncioTestCase):
    async def test_delete_by_slug_deletes_rows_then_bundles_in_order(self):
        calls = []
        result = DeleteResult(
            version_count=2,
            storage_keys=["module/mod_a1/aaa.js", "module/mod_a1/bbb.js"],
        )
        with patch.object(ctrl.module_service, "get_module_by_slug", return_value=_module()) as by_slug, \
             patch.object(
                 ctrl.module_service, "delete_module",
                 side_effect=lambda *a, **k: calls.append("delete_rows") or result,
             ) as del_fn, \
             patch.object(ctrl, "_delete_bundle", side_effect=lambda key: calls.append(f"delete_bundle:{key}")):
            resp = await ctrl.delete_module(ctrl.DeleteRequest(slug="finance"), _request())
        by_slug.assert_called_once_with(123, "finance")
        del_fn.assert_called_once_with(123, "mod_a1")
        self.assertEqual(
            calls,
            ["delete_rows", "delete_bundle:module/mod_a1/aaa.js", "delete_bundle:module/mod_a1/bbb.js"],
        )
        # deleted_versions is the row count; storage_keys is the object-key list.
        self.assertEqual(resp["deleted_versions"], 2)
        self.assertEqual(resp["storage_keys"], ["module/mod_a1/aaa.js", "module/mod_a1/bbb.js"])
        self.assertEqual(resp["module_id"], "mod_a1")

    async def test_delete_reports_version_count_separately_from_object_keys(self):
        """review finding 5: one dual-half version is 1 version but 2 objects."""
        result = DeleteResult(version_count=1, storage_keys=["module/mod_a1/aaa.js", "module/mod_a1/aaa.api.zip"])
        with patch.object(ctrl.module_service, "get_module_by_slug", return_value=_module()), \
             patch.object(ctrl.module_service, "delete_module", return_value=result) as del_fn, \
             patch.object(ctrl, "_delete_bundle"):
            resp = await ctrl.delete_module(ctrl.DeleteRequest(slug="finance"), _request())
        self.assertEqual(resp["deleted_versions"], 1)
        self.assertEqual(len(resp["storage_keys"]), 2)

    async def test_delete_by_module_id(self):
        with patch.object(ctrl.module_service, "get_module", return_value=_module()), \
             patch.object(ctrl.module_service, "delete_module", return_value=DeleteResult()) as del_fn, \
             patch.object(ctrl, "_delete_bundle") as bundle_fn:
            result = await ctrl.delete_module(ctrl.DeleteRequest(module_id="mod_a1"), _request())
        del_fn.assert_called_once_with(123, "mod_a1")
        bundle_fn.assert_not_called()
        self.assertEqual(result["deleted_versions"], 0)
        self.assertEqual(result["storage_keys"], [])

    async def test_delete_requires_module_id_or_slug(self):
        with self.assertRaises(HTTPException) as ctx:
            await ctrl.delete_module(ctrl.DeleteRequest(), _request())
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_delete_unknown_module_is_404(self):
        with patch.object(ctrl.module_service, "get_module_by_slug", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                await ctrl.delete_module(ctrl.DeleteRequest(slug="nope"), _request())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_delete_bundle_local_round_trip_and_missing_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(ctrl, "S3_BUCKET", ""), \
             patch.dict("os.environ", {"Y_AGENT_MODULE_BUNDLE_DIR": tmp}):
            key = "module/mod_a1/deadbeef.js"
            ctrl._write_bundle(key, b"x")
            ctrl._delete_bundle(key)
            with self.assertRaises(HTTPException):
                ctrl._read_bundle(key)
            # Deleting an already-missing bundle must not raise.
            ctrl._delete_bundle(key)

    async def test_delete_bundle_rejects_path_escape_silently(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(ctrl, "S3_BUCKET", ""), \
             patch.dict("os.environ", {"Y_AGENT_MODULE_BUNDLE_DIR": tmp}):
            # No exception: best-effort cleanup never raises back to the caller.
            ctrl._delete_bundle("module/../../evil.js")


if __name__ == "__main__":
    unittest.main()
