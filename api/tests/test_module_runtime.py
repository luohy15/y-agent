"""Tests for the in-process module runtime (todo 3020 phase 3).

Covers loader isolation, dispatcher request.state propagation (A1), management
route precedence, and failure-isolation blast radius.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.testclient import TestClient

from api.module_runtime import loader
from api.module_runtime.dispatcher import ModuleDispatcher
from api.module_runtime.errors import (
    ModuleArchiveError,
    ModuleBackendVersionError,
    ModuleFetchError,
    ModuleHashMismatchError,
    ModuleImportError,
)
from storage.dto.module_version import ModuleVersion


def _version(**overrides) -> ModuleVersion:
    base = dict(
        version_id="ver_1",
        module_id="mod_1",
        version_no=1,
        api_sha256=None,
        api_storage_key=None,
        min_backend_version=1,
    )
    base.update(overrides)
    return ModuleVersion(**base)


def _zip_module(files: dict[str, str]) -> bytes:
    """Build a deterministic-ish zip from {arcname: text}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, text in sorted(files.items()):
            zf.writestr(name, text)
    return buf.getvalue()


def _ping_api(marker: str) -> dict[str, str]:
    return {
        "__init__.py": "# empty\n",
        "api.py": (
            "from fastapi import APIRouter, Request, Query, HTTPException\n"
            "router = APIRouter()\n"
            f"MARKER = {marker!r}\n"
            "@router.get('/ping')\n"
            "async def ping(request: Request, q: int = Query(0)):\n"
            "    if q < 0:\n"
            "        raise HTTPException(status_code=422, detail='q must be >= 0')\n"
            "    return {'marker': MARKER, 'user_id': request.state.user_id, 'q': q}\n"
            "@router.get('/root')\n"
            "async def root_info(request: Request):\n"
            "    return {'root_path': request.scope.get('root_path', None)}\n"
        ),
    }


class LoaderIsolationTest(unittest.TestCase):
    def setUp(self):
        loader.clear_cache()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.extract_root = Path(self._tmpdir.name)
        self._extract_patch = patch.object(loader, "EXTRACT_ROOT", self.extract_root)
        self._extract_patch.start()

    def tearDown(self):
        self._extract_patch.stop()
        # Drop any ymod_* packages this test registered.
        for key in list(sys.modules):
            if key.startswith("ymod_"):
                sys.modules.pop(key, None)
        loader.clear_cache()
        self._tmpdir.cleanup()

    def test_two_builds_of_one_slug_coexist(self):
        bytes_a = _zip_module(_ping_api("A"))
        bytes_b = _zip_module(_ping_api("B"))
        sha_a = hashlib.sha256(bytes_a).hexdigest()
        sha_b = hashlib.sha256(bytes_b).hexdigest()
        self.assertNotEqual(sha_a, sha_b)

        loaded_a = loader.load_from_bytes(
            slug="scratch",
            version=_version(version_id="va", version_no=1, api_sha256=sha_a),
            api_bytes=bytes_a,
            expected_sha256=sha_a,
        )
        loaded_b = loader.load_from_bytes(
            slug="scratch",
            version=_version(version_id="vb", version_no=2, api_sha256=sha_b),
            api_bytes=bytes_b,
            expected_sha256=sha_b,
        )
        self.assertNotEqual(loaded_a.package_name, loaded_b.package_name)
        self.assertIn(sha_a[:12], loaded_a.package_name)
        self.assertIn(sha_b[:12], loaded_b.package_name)

        # Both packages live in sys.modules simultaneously.
        self.assertIn(loaded_a.package_name, sys.modules)
        self.assertIn(loaded_b.package_name, sys.modules)
        self.assertEqual(
            sys.modules[f"{loaded_a.package_name}.api"].MARKER, "A"
        )
        self.assertEqual(
            sys.modules[f"{loaded_b.package_name}.api"].MARKER, "B"
        )

        # Cache hit on re-load of the same hash.
        again = loader.load_from_bytes(
            slug="scratch",
            version=_version(version_id="va", version_no=1, api_sha256=sha_a),
            api_bytes=bytes_a,
            expected_sha256=sha_a,
        )
        self.assertIs(again, loaded_a)
        self.assertEqual(loader.cache_size(), 2)

    def test_package_name_uses_full_digest_so_shared_prefix_cannot_collide(self):
        """review finding 4: two digests sharing the first 12 hex chars must
        still get distinct sys.modules packages, so a full-hash cache miss for
        the second can never reuse the first package's imported code."""
        prefix = "a" * 12
        sha_a = prefix + "1" * 52
        sha_b = prefix + "2" * 52
        assert sha_a[:12] == sha_b[:12] and sha_a != sha_b
        self.assertNotEqual(
            loader.package_name_for("scratch", sha_a),
            loader.package_name_for("scratch", sha_b),
        )
        self.assertIn(sha_a, loader.package_name_for("scratch", sha_a))

    def test_hash_mismatch_refuses_extract(self):
        api_bytes = _zip_module(_ping_api("X"))
        with self.assertRaises(ModuleHashMismatchError) as ctx:
            loader.load_from_bytes(
                slug="scratch",
                version=_version(api_sha256="0" * 64),
                api_bytes=api_bytes,
                expected_sha256="0" * 64,
            )
        self.assertEqual(ctx.exception.kind, "hash_mismatch")
        self.assertEqual(loader.cache_size(), 0)
        # Nothing extracted under /tmp/ymod for the bogus hash.
        self.assertFalse((self.extract_root / ("0" * 64)).exists())

    def test_backend_version_gate_rejects_a_newer_floor(self):
        """A module whose min_backend_version exceeds the host contract is
        rejected clearly, before any extraction/import (todo 3028 v2)."""
        api_bytes = _zip_module(_ping_api("X"))
        sha = hashlib.sha256(api_bytes).hexdigest()
        with self.assertRaises(ModuleBackendVersionError) as ctx:
            loader.load_from_bytes(
                slug="scratch",
                version=_version(api_sha256=sha, min_backend_version=99),
                api_bytes=api_bytes,
                expected_sha256=sha,
            )
        self.assertEqual(ctx.exception.kind, "backend_version")
        self.assertIn("requires backend contract", str(ctx.exception))
        self.assertEqual(loader.cache_size(), 0)

    def test_backend_version_gate_boundary_tracks_the_host_contract(self):
        """The gate is `min_backend_version > host` → reject. Binding to the
        real BACKEND_CONTRACT_VERSION proves a module at exactly the host's
        floor loads (asserted by cache size), and one requiring one more is
        clearly rejected."""
        from agent.module_host import BACKEND_CONTRACT_VERSION

        api_bytes = _zip_module(_ping_api("X"))
        sha = hashlib.sha256(api_bytes).hexdigest()

        # A module pinned to exactly the host's contract loads and caches.
        loaded = loader.load_from_bytes(
            slug="scratch",
            version=_version(api_sha256=sha, min_backend_version=BACKEND_CONTRACT_VERSION),
            api_bytes=api_bytes,
            expected_sha256=sha,
        )
        self.assertEqual(loader.cache_size(), 1)
        self.assertEqual(loaded.version.min_backend_version, BACKEND_CONTRACT_VERSION)

        # One requiring one more than the host is clearly rejected.
        with self.assertRaises(ModuleBackendVersionError) as ctx:
            loader.load_from_bytes(
                slug="scratch",
                version=_version(
                    api_sha256=sha, min_backend_version=BACKEND_CONTRACT_VERSION + 1
                ),
                api_bytes=api_bytes,
                expected_sha256=sha,
            )
        self.assertEqual(ctx.exception.kind, "backend_version")

    def test_backend_version_gate_older_host_rejects_a_v2_module(self):
        """An older (v1) host rejects a v2 module clearly, and still accepts a
        finance-style v1 module. This is the literal 'older host, newer
        module' case the plan asks tests to prove, not just the (host, host+1)
        comparison."""
        api_bytes = _zip_module(_ping_api("X"))
        sha = hashlib.sha256(api_bytes).hexdigest()

        # Simulate the previous host release: contract version 1.
        with patch.object(loader, "BACKEND_CONTRACT_VERSION", 1):
            # min_backend_version=2 (a bot contract-v2 bundle) is rejected.
            with self.assertRaises(ModuleBackendVersionError) as ctx:
                loader.load_from_bytes(
                    slug="scratch",
                    version=_version(api_sha256=sha, min_backend_version=2),
                    api_bytes=api_bytes,
                    expected_sha256=sha,
                )
            self.assertEqual(ctx.exception.kind, "backend_version")
            self.assertIn("requires backend contract >= 2, host has 1", str(ctx.exception))

            # finance keeps declaring min_backend_version=1 and still loads.
            loader.load_from_bytes(
                slug="scratch",
                version=_version(api_sha256=sha, min_backend_version=1),
                api_bytes=api_bytes,
                expected_sha256=sha,
            )
            self.assertGreaterEqual(loader.cache_size(), 1)

            # ... and by the current (v2) host likewise.
        loader.load_from_bytes(
            slug="scratch",
            version=_version(api_sha256=sha, min_backend_version=1),
            api_bytes=api_bytes,
            expected_sha256=sha,
        )
        self.assertGreaterEqual(loader.cache_size(), 1)

    def test_import_error_on_missing_router(self):
        api_bytes = _zip_module({
            "__init__.py": "# empty\n",
            "api.py": "x = 1\n",
        })
        sha = hashlib.sha256(api_bytes).hexdigest()
        with self.assertRaises(ModuleImportError) as ctx:
            loader.load_from_bytes(
                slug="scratch",
                version=_version(api_sha256=sha),
                api_bytes=api_bytes,
                expected_sha256=sha,
            )
        self.assertEqual(ctx.exception.kind, "import")
        self.assertIn("router", str(ctx.exception))

    def test_init_must_not_import_cli(self):
        api_bytes = _zip_module({
            "__init__.py": "from . import cli  # noqa\n",
            "api.py": (
                "from fastapi import APIRouter\n"
                "router = APIRouter()\n"
            ),
            "cli.py": "group = None\n",
        })
        sha = hashlib.sha256(api_bytes).hexdigest()
        with self.assertRaises(ModuleImportError) as ctx:
            loader.load_from_bytes(
                slug="scratch",
                version=_version(api_sha256=sha),
                api_bytes=api_bytes,
                expected_sha256=sha,
            )
        self.assertIn("empty", str(ctx.exception).lower())

    def test_importing_api_does_not_import_cli(self):
        api_bytes = _zip_module({
            "__init__.py": "# empty\n",
            "api.py": (
                "from fastapi import APIRouter\n"
                "router = APIRouter()\n"
                "@router.get('/ping')\n"
                "async def ping():\n"
                "    return {'ok': True}\n"
            ),
            "cli.py": (
                "RAISED = True\n"
                "raise RuntimeError('cli should not load')\n"
            ),
        })
        sha = hashlib.sha256(api_bytes).hexdigest()
        loaded = loader.load_from_bytes(
            slug="scratch",
            version=_version(api_sha256=sha),
            api_bytes=api_bytes,
            expected_sha256=sha,
        )
        self.assertNotIn(f"{loaded.package_name}.cli", sys.modules)


def _entities_columns_api(marker: str, extra_column: bool) -> dict[str, str]:
    """A module build that declares a table named `item` against its own
    DeclarativeBase and exposes its column names over HTTP, so two builds
    with the *same* table name can be told apart by which one actually
    answered (plan 4.5)."""
    extra_line = "    extra = Column(String, nullable=True)\n" if extra_column else ""
    return {
        "__init__.py": "# empty\n",
        "entities/__init__.py": (
            "from .base import Base\n"
            "from . import item  # noqa: F401\n"
            "metadata = Base.metadata\n"
        ),
        "entities/base.py": (
            "from sqlalchemy.orm import DeclarativeBase\n\n\n"
            "class Base(DeclarativeBase):\n"
            "    pass\n"
        ),
        "entities/item.py": (
            "from sqlalchemy import Column, Integer, String\n"
            "from .base import Base\n\n\n"
            "class Item(Base):\n"
            "    __tablename__ = 'item'\n"
            "    id = Column(Integer, primary_key=True)\n"
            "    name = Column(String)\n"
            f"{extra_line}"
        ),
        "api.py": (
            "from fastapi import APIRouter\n"
            "from .entities import metadata\n"
            f"MARKER = {marker!r}\n"
            "router = APIRouter()\n"
            "@router.get('/columns')\n"
            "async def columns():\n"
            "    return {'marker': MARKER, "
            "'columns': sorted(c.name for c in metadata.tables['item'].columns)}\n"
        ),
    }


class EntitiesMetadataIsolationTest(unittest.TestCase):
    """Plan 4.5: two builds of one module that each declare a table named
    `item` against their own DeclarativeBase must coexist in one process —
    the bug this guards against would otherwise only surface under a warm
    container's version switch in production."""

    def setUp(self):
        loader.clear_cache()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.extract_root = Path(self._tmpdir.name)
        self._extract_patch = patch.object(loader, "EXTRACT_ROOT", self.extract_root)
        self._extract_patch.start()

    def tearDown(self):
        self._extract_patch.stop()
        for key in list(sys.modules):
            if key.startswith("ymod_"):
                sys.modules.pop(key, None)
        loader.clear_cache()
        self._tmpdir.cleanup()

    def test_two_versions_same_table_name_do_not_collide(self):
        bytes_a = _zip_module(_entities_columns_api("A", extra_column=False))
        bytes_b = _zip_module(_entities_columns_api("B", extra_column=True))
        sha_a = hashlib.sha256(bytes_a).hexdigest()
        sha_b = hashlib.sha256(bytes_b).hexdigest()
        self.assertNotEqual(sha_a, sha_b)

        # Loading both must not raise (in particular no InvalidRequestError
        # from a shared MetaData/DeclarativeBase seeing 'item' twice): each
        # version owns its own Base, so there is no shared registry to collide on.
        loaded_a = loader.load_from_bytes(
            slug="scratch",
            version=_version(version_id="va", version_no=1, api_sha256=sha_a),
            api_bytes=bytes_a,
            expected_sha256=sha_a,
        )
        loaded_b = loader.load_from_bytes(
            slug="scratch",
            version=_version(version_id="vb", version_no=2, api_sha256=sha_b),
            api_bytes=bytes_b,
            expected_sha256=sha_b,
        )

        client_a = TestClient(loaded_a.app)
        client_b = TestClient(loaded_b.app)
        self.assertEqual(
            client_a.get("/columns").json(), {"marker": "A", "columns": ["id", "name"]}
        )
        self.assertEqual(
            client_b.get("/columns").json(),
            {"marker": "B", "columns": ["extra", "id", "name"]},
        )

        # Each sub-app answers from its own build: distinct metadata/table objects.
        entities_a = sys.modules[f"{loaded_a.package_name}.entities"]
        entities_b = sys.modules[f"{loaded_b.package_name}.entities"]
        self.assertIsNot(entities_a.metadata, entities_b.metadata)
        self.assertIsNot(entities_a.metadata.tables["item"], entities_b.metadata.tables["item"])

    def test_preflight_import_reads_entities_metadata_for_a_scratch_module(self):
        """import_candidate_for_preflight (D7) is the same import path — used
        directly here so the publish-time preflight is covered independent of
        the controller wiring."""
        api_bytes = _zip_module(_entities_columns_api("solo", extra_column=False))
        pkg_name, router, metadata = loader.import_candidate_for_preflight("scratch2", api_bytes)
        self.assertIsNotNone(metadata)
        self.assertIn("item", metadata.tables)
        self.assertEqual(
            sorted(c.name for c in metadata.tables["item"].columns), ["id", "name"]
        )
        from fastapi import APIRouter as _APIRouter

        self.assertIsInstance(router, _APIRouter)

    def test_preflight_import_returns_none_metadata_when_no_entities(self):
        api_bytes = _zip_module(_ping_api("no-entities"))
        _pkg_name, _router, metadata = loader.import_candidate_for_preflight(
            "scratch3", api_bytes
        )
        self.assertIsNone(metadata)

    def test_failed_preflight_evicts_all_candidate_modules(self):
        api_bytes = _zip_module({
            "__init__.py": "# empty\n",
            "api.py": "from fastapi import APIRouter\nrouter = APIRouter()\n",
            "entities/__init__.py": "from . import broken\n",
            "entities/broken.py": "raise RuntimeError('broken entities')\n",
        })
        pkg_name = loader.package_name_for("scratch4", hashlib.sha256(api_bytes).hexdigest())
        with self.assertRaises(ModuleImportError):
            loader.import_candidate_for_preflight("scratch4", api_bytes)
        self.assertFalse(any(key == pkg_name or key.startswith(pkg_name + ".") for key in sys.modules))



class ArchiveSafetyTest(unittest.TestCase):
    """review finding 3: the validating extractor rejects traversal, duplicate
    names, special files, and size/count overflows before writing anything."""

    def setUp(self):
        loader.clear_cache()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.extract_root = Path(self._tmpdir.name)
        self._extract_patch = patch.object(loader, "EXTRACT_ROOT", self.extract_root)
        self._extract_patch.start()

    def tearDown(self):
        self._extract_patch.stop()
        loader.clear_cache()
        self._tmpdir.cleanup()

    def _expect_archive_error(self, files):
        zip_bytes = _zip_module(files)
        sha = hashlib.sha256(zip_bytes).hexdigest()
        with self.assertRaises(ModuleArchiveError) as ctx:
            loader.load_from_bytes(
                slug="scratch",
                version=_version(api_sha256=sha),
                api_bytes=zip_bytes,
                expected_sha256=sha,
            )
        self.assertEqual(ctx.exception.kind, "archive")
        # The per-hash root dir is created before validation, but no member
        # must be written beneath it (or anywhere) for a rejected archive.
        root = loader.extract_root_for(sha)
        self.assertTrue(root.is_dir())
        self.assertEqual(list(root.rglob("*")), [])

    def test_rejects_parent_traversal_member(self):
        self._expect_archive_error({"../evil.py": "x=1\n", "__init__.py": "# e\n"})

    def test_rejects_absolute_path_member(self):
        self._expect_archive_error({"/tmp/evil.py": "x=1\n", "__init__.py": "# e\n"})

    def test_rejects_windows_backslash_member(self):
        self._expect_archive_error({"..\\evil.py": "x=1\n", "__init__.py": "# e\n"})

    def test_rejects_duplicate_members(self):
        # A dict literal cannot hold a duplicate key, so build the zip with the
        # same arcname written twice explicitly to exercise the duplicate check.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("__init__.py", "# e\n")
            zf.writestr("a.py", "x=1\n")
            zf.writestr("a.py", "x=2\n")
        zip_bytes = buf.getvalue()
        sha = hashlib.sha256(zip_bytes).hexdigest()
        with self.assertRaises(ModuleArchiveError) as ctx:
            loader.load_from_bytes(
                slug="scratch",
                version=_version(api_sha256=sha),
                api_bytes=zip_bytes,
                expected_sha256=sha,
            )
        self.assertEqual(ctx.exception.kind, "archive")
        root = loader.extract_root_for(sha)
        self.assertEqual(list(root.rglob("*")), [])

    def test_rejects_too_many_members(self):
        # Build a legit multi-file zip, then enforce a tiny member cap so the
        # count check triggers without materializing thousands of files.
        files = {f"m{i}.py": "# f\n" for i in range(20)}
        files["__init__.py"] = "# e\n"
        zip_bytes = _zip_module(files)
        sha = hashlib.sha256(zip_bytes).hexdigest()
        with patch.object(loader, "MAX_ZIP_MEMBERS", 5):
            with self.assertRaises(ModuleArchiveError) as ctx:
                loader.load_from_bytes(
                    slug="scratch",
                    version=_version(api_sha256=sha),
                    api_bytes=zip_bytes,
                    expected_sha256=sha,
                )
        self.assertEqual(ctx.exception.kind, "archive")
        root = loader.extract_root_for(sha)
        self.assertEqual(list(root.rglob("*")), [])

    def test_rejects_excessive_uncompressed_size(self):
        files = {"__init__.py": "# e\n", "big.py": ("x" * (2 * 1024 * 1024)) + "\n"}
        zip_bytes = _zip_module(files)
        sha = hashlib.sha256(zip_bytes).hexdigest()
        with patch.object(loader, "MAX_UNCOMPRESSED_BYTES", 1024):
            with self.assertRaises(ModuleArchiveError) as ctx:
                loader.load_from_bytes(
                    slug="scratch",
                    version=_version(api_sha256=sha),
                    api_bytes=zip_bytes,
                    expected_sha256=sha,
                )
        self.assertEqual(ctx.exception.kind, "archive")
        root = loader.extract_root_for(sha)
        self.assertEqual(list(root.rglob("*")), [])

    def test_clean_nested_bundle_still_extracts_beneath_hash_root(self):
        zip_bytes = _zip_module(_ping_api("nested"))
        sha = hashlib.sha256(zip_bytes).hexdigest()
        loaded = loader.load_from_bytes(
            slug="scratch",
            version=_version(api_sha256=sha),
            api_bytes=zip_bytes,
            expected_sha256=sha,
        )
        self.assertIn(sha, loaded.package_name)
        self.assertTrue((loader.extract_root_for(sha) / "api.py").is_file())


class DispatcherTest(unittest.TestCase):
    """A1 + management precedence + Query/HTTPException behaviour."""

    def setUp(self):
        loader.clear_cache()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.extract_root = Path(self._tmpdir.name)
        self._extract_patch = patch.object(loader, "EXTRACT_ROOT", self.extract_root)
        self._extract_patch.start()
        # FakeAuth signs in user 42; make that the trusted owner for the gate.
        self._owner_patch = patch(
            "api.module_runtime.dispatcher.default_owner_user_id", return_value=42
        )
        self._owner_patch.start()

        api_bytes = _zip_module(_ping_api("live"))
        self.sha = hashlib.sha256(api_bytes).hexdigest()
        self.loaded = loader.load_from_bytes(
            slug="scratch-mod",
            version=_version(
                version_id="ver_live",
                version_no=3,
                api_sha256=self.sha,
                api_storage_key=f"module/mod/{self.sha}.api.zip",
            ),
            api_bytes=api_bytes,
            expected_sha256=self.sha,
        )

        def fake_load(user_id, slug):
            if slug != "scratch-mod":
                from api.module_runtime.errors import ModuleNotFoundError
                raise ModuleNotFoundError(slug, f"no {slug}")
            return self.loaded

        self.dispatcher = ModuleDispatcher(load_fn=fake_load)

        # Build a mini app that mirrors production: management router first,
        # then the mount. Auth middleware sets request.state.user_id.
        from starlette.middleware.base import BaseHTTPMiddleware

        class FakeAuth(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state.user_id = 42
                request.state.email = "roy@example.com"
                return await call_next(request)

        app = FastAPI()
        app.add_middleware(FakeAuth)

        from fastapi import APIRouter as AR
        mgmt = AR(prefix="/api/module")
        @mgmt.get("/list")
        async def list_modules(request: Request):
            return [{"slug": "from-management", "user_id": request.state.user_id}]
        app.include_router(mgmt)
        app.mount("/api/module", self.dispatcher)
        self.client = TestClient(app)

    def tearDown(self):
        self._owner_patch.stop()
        self._extract_patch.stop()
        for key in list(sys.modules):
            if key.startswith("ymod_"):
                sys.modules.pop(key, None)
        loader.clear_cache()
        self._tmpdir.cleanup()

    def test_a1_request_state_user_id_reaches_module_handler(self):
        """A1: AuthMiddleware-set request.state survives into the mounted sub-app."""
        resp = self.client.get("/api/module/scratch-mod/ping")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["user_id"], 42)
        self.assertEqual(body["marker"], "live")

    def test_non_owner_backend_dispatch_is_403(self):
        """review finding 1: an authenticated account other than the trusted
        owner cannot execute a backend half."""
        resp = self.client.get("/api/module/scratch-mod/ping")
        self.assertEqual(resp.status_code, 200)  # owner (42) is fine

        # A different authenticated user must be refused before any load.
        with patch(
            "api.module_runtime.dispatcher.default_owner_user_id", return_value=99
        ):
            resp = self.client.get("/api/module/scratch-mod/ping")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("maintainer", resp.json()["detail"])

    def test_root_path_is_mount_prefix_plus_slug_not_duplicated(self):
        """review finding 6: root_path is /api/module/<slug>, not a duplicated prefix."""
        resp = self.client.get("/api/module/scratch-mod/root")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["root_path"], "/api/module/scratch-mod")

    def test_query_validation_and_http_exception(self):
        resp = self.client.get("/api/module/scratch-mod/ping", params={"q": 7})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["q"], 7)

        # FastAPI Query type coercion: non-int -> 422 from the sub-app.
        resp = self.client.get("/api/module/scratch-mod/ping", params={"q": "nope"})
        self.assertEqual(resp.status_code, 422)

        # Module-raised HTTPException.
        resp = self.client.get("/api/module/scratch-mod/ping", params={"q": -1})
        self.assertEqual(resp.status_code, 422)
        self.assertIn("q must be", resp.json()["detail"])

    def test_management_list_still_reaches_management_endpoint(self):
        resp = self.client.get("/api/module/list")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body[0]["slug"], "from-management")
        self.assertEqual(body[0]["user_id"], 42)


class FailureIsolationTest(unittest.TestCase):
    """Plan 3.6: a broken module's route errors; an unrelated endpoint answers 200."""

    def setUp(self):
        loader.clear_cache()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.extract_root = Path(self._tmpdir.name)
        self._extract_patch = patch.object(loader, "EXTRACT_ROOT", self.extract_root)
        self._extract_patch.start()
        # FakeAuth signs in user 1; make that the trusted owner for the gate.
        self._owner_patch = patch(
            "api.module_runtime.dispatcher.default_owner_user_id", return_value=1
        )
        self._owner_patch.start()

        from starlette.middleware.base import BaseHTTPMiddleware

        class FakeAuth(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                request.state.user_id = 1
                return await call_next(request)

        self.app = FastAPI()
        self.app.add_middleware(FakeAuth)

        @self.app.get("/api/health")
        async def health():
            return {"ok": True}

    def tearDown(self):
        self._owner_patch.stop()
        self._extract_patch.stop()
        for key in list(sys.modules):
            if key.startswith("ymod_"):
                sys.modules.pop(key, None)
        loader.clear_cache()
        self._tmpdir.cleanup()

    def _client_with(self, load_fn):
        self.app.mount("/api/module", ModuleDispatcher(load_fn=load_fn))
        return TestClient(self.app)

    def test_fetch_failure_isolates(self):
        def load(user_id, slug):
            raise ModuleFetchError(slug, "s3 down", version_id="v1", version_no=1)

        client = self._client_with(load)
        bad = client.get("/api/module/broken/ping")
        self.assertEqual(bad.status_code, 502)
        self.assertEqual(bad.json()["kind"], "fetch")
        self.assertEqual(bad.json()["slug"], "broken")
        self.assertEqual(client.get("/api/health").status_code, 200)

    def test_hash_mismatch_isolates(self):
        def load(user_id, slug):
            raise ModuleHashMismatchError(slug, "hash mismatch", version_id="v1", version_no=2)

        client = self._client_with(load)
        bad = client.get("/api/module/broken/ping")
        self.assertEqual(bad.status_code, 502)
        self.assertEqual(bad.json()["kind"], "hash_mismatch")
        self.assertEqual(client.get("/api/health").json()["ok"], True)

    def test_import_error_isolates(self):
        def load(user_id, slug):
            raise ModuleImportError(slug, "syntax error", version_id="v1", version_no=3)

        client = self._client_with(load)
        bad = client.get("/api/module/broken/ping")
        self.assertEqual(bad.status_code, 502)
        self.assertEqual(bad.json()["kind"], "import")
        self.assertEqual(client.get("/api/health").status_code, 200)

    def test_backend_version_skew_isolates(self):
        def load(user_id, slug):
            raise ModuleBackendVersionError(
                slug, "needs backend 9", version_id="v1", version_no=4
            )

        client = self._client_with(load)
        bad = client.get("/api/module/broken/ping")
        self.assertEqual(bad.status_code, 409)
        self.assertEqual(bad.json()["kind"], "backend_version")
        self.assertEqual(client.get("/api/health").status_code, 200)

    def test_archive_error_isolates(self):
        """review finding 3: an unsafe archive 400s; an unrelated route stays healthy."""
        def load(user_id, slug):
            raise ModuleArchiveError(slug, "zip member escapes the extraction root")

        client = self._client_with(load)
        bad = client.get("/api/module/broken/ping")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.json()["kind"], "archive")
        self.assertEqual(client.get("/api/health").json()["ok"], True)


if __name__ == "__main__":
    unittest.main()
