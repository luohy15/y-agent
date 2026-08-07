"""Local filesystem import of a module package (CLI half + common vendoring).

Used by the lazy CLI registration (phase 5) and by phase-3 tests that prove
`from .common import …` resolves against `<MODULE_SOURCE_ROOT>/common` without
a publish step (plan D12 / 3.5).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Optional

from ._paths import modules_dir, source_dir


def package_name_for(slug: str) -> str:
    # Local (unpublished) packages use a stable name so CLI state survives
    # across invocations in the same process; the published loader uses a
    # content-hash-qualified name instead.
    return f"ymod_local_{slug.replace('-', '_')}"


def validate_local_package_root(slug: str) -> Path:
    """Require the D11 empty/comments-only root before importing package code."""
    root = source_dir(slug)
    if not root.is_dir():
        raise FileNotFoundError(f"module source not found: {root}")
    init_py = root / "__init__.py"
    if not init_py.is_file():
        raise FileNotFoundError(
            f"module {slug!r} is missing __init__.py (required for local import)"
        )
    init_text = init_py.read_text(encoding="utf-8").strip()
    if init_text and not all(
        line.lstrip().startswith("#") or not line.strip() for line in init_text.splitlines()
    ):
        raise ValueError(
            f"__init__.py for {slug} must stay empty; API and CLI halves must load independently"
        )
    return root


def import_local_module(slug: str, *, package_name: Optional[str] = None) -> ModuleType:
    """Import `<MODULE_SOURCE_ROOT>/<slug>/` as a top-level package.

    Registers `<pkg>.common` from `code/y-module/common/` when that directory exists
    and the slug is not itself `common` (plan D12 CLI-side path injection).
    """
    root = validate_local_package_root(slug)

    pkg_name = package_name or package_name_for(slug)
    if pkg_name in sys.modules:
        _ensure_common(pkg_name, slug)
        return sys.modules[pkg_name]

    init_py = root / "__init__.py"
    if not init_py.is_file():
        # Tolerate a missing __init__ for UI-only scaffolds; write nothing —
        # importlib needs a file, so use an empty in-memory load via a temp
        # marker only when api/cli submodules need the package. Prefer requiring
        # the file so the scaffold stays honest.
        raise FileNotFoundError(
            f"module {slug!r} is missing __init__.py (required for local import)"
        )

    spec = importlib.util.spec_from_file_location(
        pkg_name,
        init_py,
        submodule_search_locations=[str(root)],
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"could not build import spec for module {slug!r}")
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = pkg
    try:
        spec.loader.exec_module(pkg)
    except Exception:
        sys.modules.pop(pkg_name, None)
        raise

    _ensure_common(pkg_name, slug)
    return pkg


def import_local_cli(slug: str):
    """Import `<pkg>.cli` for a local module source. Returns the module."""
    pkg = import_local_module(slug)
    return importlib.import_module(f"{pkg.__name__}.cli")


def import_local_api(slug: str):
    """Import `<pkg>.api` for a local module source. Returns the module."""
    pkg = import_local_module(slug)
    return importlib.import_module(f"{pkg.__name__}.api")


def import_local_entities(slug: str):
    """Import `<pkg>.entities` for a local module source, or None if the
    module owns no tables (plan 4.2/D11: entities/ is optional; its absence
    means "this module owns no tables", not an error)."""
    pkg = import_local_module(slug)
    try:
        return importlib.import_module(f"{pkg.__name__}.entities")
    except ModuleNotFoundError as exc:
        if exc.name == f"{pkg.__name__}.entities":
            return None
        raise


def _ensure_common(pkg_name: str, slug: str) -> None:
    if slug == "common":
        return
    common_key = f"{pkg_name}.common"
    if common_key in sys.modules:
        return
    common_root = modules_dir() / "common"
    if not common_root.is_dir():
        return
    init_py = common_root / "__init__.py"
    if not init_py.is_file():
        return
    spec = importlib.util.spec_from_file_location(
        common_key,
        init_py,
        submodule_search_locations=[str(common_root)],
    )
    if spec is None or spec.loader is None:
        return
    mod = importlib.util.module_from_spec(spec)
    sys.modules[common_key] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(common_key, None)
        raise
    # Also bind as attribute on the parent package so `from .common import x`
    # finds it via normal package attribute lookup after relative import setup.
    parent = sys.modules.get(pkg_name)
    if parent is not None:
        setattr(parent, "common", mod)
