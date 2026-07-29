"""Paths for UI artifact sources and the materialized SDK on the VM."""

from __future__ import annotations

import os
import re
from pathlib import Path

# Must match api/controller/ui_artifact.py SLUG_RE exactly so create/publish
# cannot accept a slug the API will reject (or reject one the API accepts).
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def agent_home() -> Path:
    return Path(os.path.expanduser(os.environ.get("Y_AGENT_HOME", "~/.y-agent")))


def ui_dir() -> Path:
    """Artifact sources live under $Y_AGENT_HOME/ui (plan: ~/luohy15/ui/)."""
    return agent_home() / "ui"


def sdk_dir() -> Path:
    return ui_dir() / ".sdk"


def source_path(slug: str) -> Path:
    return ui_dir() / f"{slug}.tsx"


def meta_path(slug: str) -> Path:
    return ui_dir() / f"{slug}.json"


def build_out_dir(slug: str) -> Path:
    return ui_dir() / ".build" / slug


def validate_slug(slug: str) -> str:
    if not SLUG_RE.match(slug):
        raise ValueError(
            f"invalid slug {slug!r}: must match "
            r"^[a-z0-9][a-z0-9-]{0,62}$ "
            "(lowercase alphanumerics and hyphens, max 63 chars)"
        )
    return slug
