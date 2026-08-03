"""Typed load/dispatch failures for the module runtime.

Each kind maps to a distinct error surface so a broken module names the
failure without taking down unrelated routes (plan 3.6).
"""

from __future__ import annotations

from typing import Optional


class ModuleRuntimeError(Exception):
    """Base class: always carries slug + kind so the dispatcher can format a response."""

    kind: str = "runtime"

    def __init__(
        self,
        slug: str,
        message: str,
        *,
        version_id: Optional[str] = None,
        version_no: Optional[int] = None,
    ):
        self.slug = slug
        self.version_id = version_id
        self.version_no = version_no
        super().__init__(message)

    def detail(self) -> dict:
        body = {
            "slug": self.slug,
            "kind": self.kind,
            "detail": str(self),
        }
        if self.version_id is not None:
            body["version_id"] = self.version_id
        if self.version_no is not None:
            body["version_no"] = self.version_no
        return body


class ModuleFetchError(ModuleRuntimeError):
    kind = "fetch"


class ModuleHashMismatchError(ModuleRuntimeError):
    kind = "hash_mismatch"


class ModuleImportError(ModuleRuntimeError):
    kind = "import"


class ModuleBackendVersionError(ModuleRuntimeError):
    kind = "backend_version"


class ModuleNotFoundError(ModuleRuntimeError):
    kind = "not_found"


class ModuleDisabledError(ModuleRuntimeError):
    kind = "disabled"


class ModuleNoApiError(ModuleRuntimeError):
    kind = "no_api"


class ModuleArchiveError(ModuleRuntimeError):
    """The uploaded/loaded API zip violates the extraction safety policy."""
    kind = "archive"
