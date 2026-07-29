"""Run the VM-side artifact build (esbuild + Tailwind + scope + inline CSS)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ._paths import build_out_dir, source_path, ui_dir
from ._sdk import ensure_sdk


def build_artifact(slug: str) -> dict:
    """Build <slug>.tsx. Returns the manifest dict (sha256, bundle path, …).

    On esbuild/tailwind failure, raises RuntimeError with the compiler message
    and does not touch any remote state (PRD story 6).
    """
    src = source_path(slug)
    if not src.is_file():
        raise FileNotFoundError(f"source not found: {src} (run: y ui create {slug})")

    sdk = ensure_sdk()
    out = build_out_dir(slug)
    out.mkdir(parents=True, exist_ok=True)

    build_js = sdk / "build.mjs"
    cmd = [
        "node",
        str(build_js),
        "--slug",
        slug,
        "--src",
        str(ui_dir()),
        "--out",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Prefer stderr (esbuild/tailwind diagnostics); fall back to stdout.
        msg = (result.stderr or result.stdout or "build failed").rstrip()
        raise RuntimeError(msg)

    # build.mjs prints one JSON object on stdout (may be preceded by npm noise).
    line = _last_json_line(result.stdout)
    if not line:
        raise RuntimeError(
            "build produced no manifest\n" + (result.stdout or result.stderr or "")
        )
    try:
        manifest = json.loads(line)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid build manifest: {line!r}") from exc

    bundle = Path(manifest["bundle"])
    if not bundle.is_file():
        raise RuntimeError(f"build claimed bundle at {bundle} but file is missing")
    return manifest


def _last_json_line(stdout: str) -> str | None:
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return line
    return None


def print_build_error(exc: BaseException) -> None:
    print(str(exc), file=sys.stderr)
