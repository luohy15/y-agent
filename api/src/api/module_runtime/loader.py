"""Load a module's published API half into an in-process, version-isolated package.

Cache key is the content hash (api_sha256). Two builds of the same slug coexist
in a warm container; rollback to an already-loaded version is free (plan D11).
"""

from __future__ import annotations

import builtins
import hashlib
import importlib
import importlib.util
import posixpath
import shutil
import stat
import sys
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, FastAPI

from agent.module_host import BACKEND_CONTRACT_VERSION
from api.module_runtime.errors import (
    ModuleArchiveError,
    ModuleBackendVersionError,
    ModuleDisabledError,
    ModuleFetchError,
    ModuleHashMismatchError,
    ModuleImportError,
    ModuleNoApiError,
    ModuleNotFoundError,
    ModuleRuntimeError,
)
from storage.dto.module_version import ModuleVersion
from storage.service import module as module_service

# Content-addressed extract root. Lambda /tmp is writable (plan A3).
EXTRACT_ROOT = Path("/tmp/ymod")

# Extraction safety limits (Lambda /tmp = 512 MB; the bundle store is small,
# so these only guard against malformed or hostile archives uploaded by the
# one trusted author).
MAX_ZIP_MEMBERS = 2_000
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024  # aggregate uncompressed size


@dataclass
class LoadedModule:
    slug: str
    version: ModuleVersion
    package_name: str
    router: APIRouter
    app: FastAPI


# api_sha256 -> LoadedModule. Process-local; cold starts start empty (lazy).
_cache: dict[str, LoadedModule] = {}


def clear_cache() -> None:
    """Test helper: drop every cached load. Does not unload sys.modules entries."""
    _cache.clear()


def cache_size() -> int:
    return len(_cache)


def package_name_for(slug: str, api_sha256: str) -> str:
    # Full digest, not a truncated prefix: two bundles whose SHA-256 share a
    # short prefix must still get distinct sys.modules packages so a "already
    # imported" lookup under the second full hash can never reuse the first
    # package's code (review finding 4).
    return f"ymod_{slug}_{api_sha256}"


def extract_root_for(api_sha256: str) -> Path:
    return EXTRACT_ROOT / api_sha256


def load_from_bytes(
    *,
    slug: str,
    version: ModuleVersion,
    api_bytes: bytes,
    expected_sha256: str,
    cache: bool = True,
) -> LoadedModule:
    """Materialize + import a module API half from already-fetched bytes.

    Verifies sha256 before extracting. Safe to call from tests without the
    bundle store; the request path goes through load_active_module.
    """
    actual = hashlib.sha256(api_bytes).hexdigest()
    if actual != expected_sha256.strip().lower():
        raise ModuleHashMismatchError(
            slug,
            f"api bundle hash mismatch for {slug} v{version.version_no}: "
            f"expected {expected_sha256[:12]}… got {actual[:12]}…",
            version_id=version.version_id,
            version_no=version.version_no,
        )

    if version.min_backend_version is not None and version.min_backend_version > BACKEND_CONTRACT_VERSION:
        raise ModuleBackendVersionError(
            slug,
            f"module {slug} v{version.version_no} requires backend contract "
            f">= {version.min_backend_version}, host has {BACKEND_CONTRACT_VERSION}",
            version_id=version.version_id,
            version_no=version.version_no,
        )

    cached = _cache.get(actual)
    if cache and cached is not None:
        return cached

    root = extract_root_for(actual)
    pkg_name = package_name_for(slug, actual)

    try:
        _extract_zip(api_bytes, root, slug)
        router = _import_router(slug, pkg_name, root, version)
    except ModuleRuntimeError:
        evict_package(pkg_name)
        raise
    except Exception as exc:
        evict_package(pkg_name)
        raise ModuleImportError(
            slug,
            f"import failed for {slug} v{version.version_no}: {exc}",
            version_id=version.version_id,
            version_no=version.version_no,
        ) from exc

    app = FastAPI()
    app.include_router(router)
    loaded = LoadedModule(
        slug=slug,
        version=version,
        package_name=pkg_name,
        router=router,
        app=app,
    )
    if cache:
        _cache[actual] = loaded
    return loaded


def resolve_active_version(user_id: int, slug: str) -> ModuleVersion:
    """Resolve and validate an owner's active API version without importing it."""
    module = module_service.get_module_by_slug(user_id, slug)
    if not module:
        raise ModuleNotFoundError(slug, f"module {slug!r} not found")
    if not module.enabled:
        raise ModuleDisabledError(slug, f"module {slug!r} is disabled")
    if not module.active_version_id:
        raise ModuleNoApiError(slug, f"module {slug!r} has no active version")

    version = module_service.get_version(user_id, module.active_version_id)
    if not version:
        raise ModuleNotFoundError(
            slug,
            f"active version {module.active_version_id} for {slug!r} is missing",
        )
    if not version.api_sha256 or not version.api_storage_key:
        raise ModuleNoApiError(
            slug,
            f"module {slug!r} v{version.version_no} has no API half",
            version_id=version.version_id,
            version_no=version.version_no,
        )
    return version


def load_active_module(user_id: int, slug: str) -> LoadedModule:
    """Resolve the owner's active version for slug and load its API half."""
    version = resolve_active_version(user_id, slug)

    cached = _cache.get(version.api_sha256)
    if cached is not None:
        if cached.version.version_id == version.version_id:
            return cached
        return replace(cached, version=version)

    try:
        from api.controller import module as module_ctrl

        api_bytes = module_ctrl._read_bundle(version.api_storage_key)
    except Exception as exc:
        raise ModuleFetchError(
            slug,
            f"failed to fetch API bundle for {slug} v{version.version_no}: {exc}",
            version_id=version.version_id,
            version_no=version.version_no,
        ) from exc

    return load_from_bytes(
        slug=slug,
        version=version,
        api_bytes=api_bytes,
        expected_sha256=version.api_sha256,
    )


def _extract_zip(api_bytes: bytes, root: Path, slug: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    # Re-extract only when the marker is missing so a warm container reuses the tree.
    marker = root / ".extracted"
    if marker.is_file():
        return
    import io

    root_resolved = root.resolve()
    seen: set[str] = set()
    total_uncompressed = 0
    plan: list = []
    with zipfile.ZipFile(io.BytesIO(api_bytes)) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_MEMBERS:
            raise ModuleArchiveError(
                slug,
                f"API bundle has {len(infos)} members, over the {MAX_ZIP_MEMBERS} limit",
            )
        for info in infos:
            name = info.filename
            # Reject windows-style separators / drive letters / absolute names:
            # normalization must never escape the per-hash extract root.
            if "\\" in name or name.startswith("/") or (len(name) > 1 and name[1] == ":"):
                raise ModuleArchiveError(
                    slug, f"unsafe zip member path {name!r}"
                )
            norm = posixpath.normpath(name)
            if norm in ("", "."):
                continue
            if norm == ".." or norm.startswith("../") or norm in seen:
                raise ModuleArchiveError(
                    slug, f"duplicate or traversing zip member {name!r}"
                )
            seen.add(norm)
            target = (root / norm).resolve()
            if target != root_resolved and root_resolved not in target.parents:
                raise ModuleArchiveError(
                    slug, f"zip member {name!r} escapes the extraction root"
                )
            if info.is_dir():
                plan.append(("dir", target))
                continue
            mode = (info.external_attr >> 16) & 0xFFFF
            if mode and stat.S_ISLNK(mode):
                # symlinks / special files: unsafe to materialize from an archive.
                raise ModuleArchiveError(
                    slug, f"zip member {name!r} is not a regular file"
                )
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise ModuleArchiveError(
                    slug,
                    f"API bundle uncompressed size exceeds the "
                    f"{MAX_UNCOMPRESSED_BYTES} byte limit",
                )
            plan.append(("file", info, target))
        # All members validated and the aggregate size bound satisfied:
        # only now materialize, so an oversized/unsafe archive writes nothing.
        for item in plan:
            if item[0] == "dir":
                item[1].mkdir(parents=True, exist_ok=True)
                continue
            _, info, target = item
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    marker.write_text("ok\n", encoding="utf-8")


def _prepare_package_root(
    slug: str,
    root: Path,
    *,
    version_id: Optional[str] = None,
    version_no: Optional[int] = None,
) -> Path:
    """Validate `__init__.py` (present, empty per D11) and return the adjusted
    root. Shared by the request-path loader and the publish-time preflight
    importer (`import_candidate_for_preflight`) so both exercise the exact
    same checks (plan D7)."""
    init_py = root / "__init__.py"
    if not init_py.is_file():
        # Zip may nest under a single top-level dir; accept that shape too.
        children = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
        if len(children) == 1 and (children[0] / "__init__.py").is_file():
            root = children[0]
            init_py = root / "__init__.py"
        else:
            raise ModuleImportError(
                slug,
                f"API bundle for {slug} is missing __init__.py",
                version_id=version_id,
                version_no=version_no,
            )

    # Empty __init__ is required (D11): loading .api must not pull .cli.
    init_text = init_py.read_text(encoding="utf-8").strip()
    if init_text and not all(
        line.lstrip().startswith("#") or not line.strip() for line in init_text.splitlines()
    ):
        raise ModuleImportError(
            slug,
            f"__init__.py for {slug} must stay empty; "
            "API and CLI halves must load independently",
            version_id=version_id,
            version_no=version_no,
        )
    return root


def evict_package(pkg_name: str) -> None:
    """Remove a package and every imported child from sys.modules."""
    for key in list(sys.modules):
        if key == pkg_name or key.startswith(pkg_name + "."):
            sys.modules.pop(key, None)


def _import_submodule(pkg_name: str, root: Path, dotted: str):
    """Import `<pkg_name>.<dotted>`, execing the top-level package first if it
    is not already registered under this content-hash-qualified name.

    On any failure, unregisters `pkg_name` and every submodule from
    `sys.modules` so a later retry of the same hash never reuses a
    half-imported package.
    """
    if pkg_name in sys.modules:
        # Same content hash already imported under this package name: reuse.
        return importlib.import_module(f"{pkg_name}.{dotted}")

    init_py = root / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        pkg_name,
        init_py,
        submodule_search_locations=[str(root)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not build import spec for {pkg_name}")
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = pkg
    try:
        spec.loader.exec_module(pkg)
        return importlib.import_module(f"{pkg_name}.{dotted}")
    except Exception:
        evict_package(pkg_name)
        raise


def _import_router(slug: str, pkg_name: str, root: Path, version: ModuleVersion) -> APIRouter:
    root = _prepare_package_root(
        slug, root, version_id=version.version_id, version_no=version.version_no
    )
    try:
        api_mod = _import_submodule(pkg_name, root, "api")
    except ModuleRuntimeError:
        raise
    except Exception as exc:
        raise ModuleImportError(
            slug,
            f"import failed for {slug} v{version.version_no}: {exc}",
            version_id=version.version_id,
            version_no=version.version_no,
        ) from exc

    router = getattr(api_mod, "router", None)
    if router is None:
        raise ModuleImportError(
            slug,
            f"{slug}.api does not export `router`",
            version_id=version.version_id,
            version_no=version.version_no,
        )
    if not isinstance(router, APIRouter):
        raise ModuleImportError(
            slug,
            f"{slug}.api.router is {type(router).__name__}, expected APIRouter",
            version_id=version.version_id,
            version_no=version.version_no,
        )
    return router


def import_candidate_for_preflight(
    slug: str, api_bytes: bytes, min_backend_version: Optional[int] = None
) -> tuple:
    """Load a candidate through the request loader before publishing it.

    The candidate differs only in that it has no persisted version row and is
    not inserted into the request cache. Successful preflight packages remain
    resident for request-path reuse. Every failed path evicts the entire
    content-hash-qualified package before returning an error.
    """
    actual = hashlib.sha256(api_bytes).hexdigest()
    pkg_name = package_name_for(slug, actual)
    version = ModuleVersion(
        version_id="preflight",
        module_id="preflight",
        version_no=0,
        api_sha256=actual,
        min_backend_version=min_backend_version,
    )

    try:
        loaded = load_from_bytes(
            slug=slug,
            version=version,
            api_bytes=api_bytes,
            expected_sha256=actual,
            cache=False,
        )

        # `ModuleNotFoundError` here is the module-level import of our own typed
        # error (api.module_runtime.errors.ModuleNotFoundError), which shadows
        # the builtin error importlib raises when `<pkg>.entities` is absent.
        try:
            entities_mod = importlib.import_module(f"{pkg_name}.entities")
        except builtins.ModuleNotFoundError as exc:
            if exc.name != f"{pkg_name}.entities":
                raise ModuleImportError(
                    slug, f"import failed for {slug}.entities: {exc}"
                ) from exc
            entities_mod = None
        except Exception as exc:
            raise ModuleImportError(slug, f"import failed for {slug}.entities: {exc}") from exc

        metadata = None
        if entities_mod is not None:
            metadata = getattr(entities_mod, "metadata", None)
            if metadata is None:
                raise ModuleImportError(slug, f"{slug}.entities does not export `metadata`")
        return pkg_name, loaded.router, metadata
    except Exception:
        evict_package(pkg_name)
        raise
