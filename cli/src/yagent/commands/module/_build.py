"""Run the VM-side UI build and the deterministic Python API zip build."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from ._paths import build_out_dir, modules_dir, source_dir, source_path, ui_dir
from ._sdk import ensure_sdk

# Directories / names excluded from the published API zip (plan D11).
_API_ZIP_EXCLUDE_DIRS = {
    "ui",
    "tests",
    "migration",
    "__pycache__",
    ".build",
    "node_modules",
    ".sdk",
    ".git",
}
_API_ZIP_EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def build_artifact(slug: str) -> dict:
    """Build <slug>/ui/index.tsx. Returns the manifest dict (sha256, bundle path, …).

    On esbuild/tailwind failure, raises RuntimeError with the compiler message
    and does not touch any remote state (PRD story 6).

    cwd is fixed to the SDK directory so esbuild's relative path comments (and
    therefore the bundle sha256) do not depend on the caller's working directory
    (phase-2 review finding).
    """
    src = source_path(slug)
    if not src.is_file():
        raise FileNotFoundError(f"source not found: {src} (run: y module create {slug})")

    sdk = ensure_sdk()
    out = build_out_dir(slug)
    out.mkdir(parents=True, exist_ok=True)

    build_js = sdk / "build.mjs"
    # Pass paths relative to the SDK cwd so esbuild embeds stable relative
    # comments regardless of where the user invoked `y module publish`.
    src_rel = os.path.relpath(ui_dir(slug), sdk)
    out_rel = os.path.relpath(out, sdk)
    cmd = [
        "node",
        "build.mjs",
        "--slug",
        slug,
        "--src",
        src_rel,
        "--out",
        out_rel,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(sdk))
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

    # build.mjs may emit a path relative to the SDK cwd; normalize to absolute.
    bundle = Path(manifest["bundle"])
    if not bundle.is_absolute():
        bundle = (sdk / bundle).resolve()
        manifest["bundle"] = str(bundle)
    if not bundle.is_file():
        raise RuntimeError(f"build claimed bundle at {bundle} but file is missing")
    return manifest


def build_api_bundle(slug: str) -> dict | None:
    """Zip the module's Python half. Returns None when there is no API half.

    A module has an API half when `<modules>/<slug>/api.py` exists. The zip is
    deterministic (sorted entries, fixed timestamps) so the content hash is
    stable across hosts and call sites. When `modules/common/` exists and
    `slug != "common"`, its contents are vendored as `common/` inside the zip
    (plan D12); those bytes are part of api_sha256.
    """
    root = source_dir(slug)
    api_py = root / "api.py"
    if not api_py.is_file():
        return None

    out = build_out_dir(slug)
    out.mkdir(parents=True, exist_ok=True)
    zip_path = out / f"{slug}.api.zip"

    entries: list[tuple[str, bytes]] = []

    def _add_tree(src_root: Path, arc_prefix: str = "") -> None:
        for dirpath, dirnames, filenames in os.walk(src_root):
            # Prune excluded directories in-place so os.walk skips them.
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in _API_ZIP_EXCLUDE_DIRS and not d.startswith(".")
            )
            rel_dir = os.path.relpath(dirpath, src_root)
            for name in sorted(filenames):
                if name.startswith("."):
                    continue
                if any(name.endswith(suf) for suf in _API_ZIP_EXCLUDE_SUFFIXES):
                    continue
                full = Path(dirpath) / name
                if not full.is_file():
                    continue
                rel = name if rel_dir == "." else f"{rel_dir}/{name}"
                rel = rel.replace(os.sep, "/")
                arcname = f"{arc_prefix}{rel}" if arc_prefix else rel
                entries.append((arcname, full.read_bytes()))

    _add_tree(root)

    # D12: vendor common/ into the consumer zip (not into common's own zip).
    if slug != "common":
        common_root = modules_dir() / "common"
        if common_root.is_dir():
            _add_tree(common_root, arc_prefix="common/")

    # Deterministic zip: sorted names, fixed date, no extra fields.
    entries.sort(key=lambda item: item[0])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname, data in entries:
            info = zipfile.ZipInfo(arcname)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            # Normalize permissions so host umask cannot change the hash.
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)
    api_bytes = buf.getvalue()
    zip_path.write_bytes(api_bytes)
    sha = hashlib.sha256(api_bytes).hexdigest()
    return {
        "slug": slug,
        "sha256": sha,
        "bytes": len(api_bytes),
        "bundle": str(zip_path),
        "entries": [name for name, _ in entries],
    }


def _last_json_line(stdout: str) -> str | None:
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return line
    return None


def print_build_error(exc: BaseException) -> None:
    print(str(exc), file=sys.stderr)
