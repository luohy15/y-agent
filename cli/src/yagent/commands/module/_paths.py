"""Paths for canonical module sources and the materialized SDK on the VM."""

from __future__ import annotations

import os
import re
from pathlib import Path

# Must match api/controller/module.py SLUG_RE exactly so create/publish
# cannot accept a slug the API will reject (or reject one the API accepts).
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def agent_home() -> Path:
    return Path(os.path.expanduser(os.environ.get("Y_AGENT_HOME", "~/.y-agent")))


def modules_dir() -> Path:
    """Canonical module source directory: $Y_AGENT_HOME/modules."""
    return agent_home() / "modules"


def source_dir(slug: str) -> Path:
    return modules_dir() / slug


def ui_dir(slug: str) -> Path:
    return source_dir(slug) / "ui"


def sdk_dir() -> Path:
    return modules_dir() / ".sdk"


def source_path(slug: str) -> Path:
    return ui_dir(slug) / "index.tsx"


def meta_path(slug: str) -> Path:
    return source_dir(slug) / "module.json"


def build_out_dir(slug: str) -> Path:
    return source_dir(slug) / ".build"


def validate_slug(slug: str) -> str:
    if not SLUG_RE.match(slug):
        raise ValueError(
            f"invalid slug {slug!r}: must match "
            r"^[a-z0-9][a-z0-9-]{0,62}$ "
            "(lowercase alphanumerics and hyphens, max 63 chars)"
        )
    return slug
