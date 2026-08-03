"""Materialize the in-repo SDK onto the VM under ~/…/ui/.sdk/ (decision D7)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from ._paths import sdk_dir, ui_dir

# cli/src/yagent/commands/module/_sdk.py → cli/src/yagent/sdk
_PACKAGE_SDK = Path(__file__).resolve().parents[2] / "sdk"

# Written into the materialized SDK; when it diverges from a fresh digest of
# the packaged tree, ensure_sdk re-copies (so a build.mjs / shim fix reaches
# the VM without a contract-version bump).
_DIGEST_MARKER = ".sdk-content-digest"

# Paths that are local to the VM materialization and must not participate in
# the package-content digest or be wiped as "stale package files".
_SKIP_TOP = frozenset({"node_modules", ".cache", _DIGEST_MARKER})


def package_sdk_root() -> Path:
    """Locate the SDK sources shipped as CLI package data."""
    if not _PACKAGE_SDK.is_dir():
        raise RuntimeError(f"SDK package data missing at {_PACKAGE_SDK}")
    return _PACKAGE_SDK


def load_contract() -> dict:
    contract_file = package_sdk_root() / "contract.json"
    return json.loads(contract_file.read_text(encoding="utf-8"))


def package_sdk_digest(root: Path | None = None) -> str:
    """Stable sha256 over every shipped SDK file (path + bytes, sorted).

    Excludes node_modules / .cache / the digest marker itself so a VM-side
    npm install or tailwind cache never forces a re-copy loop.
    """
    root = root or package_sdk_root()
    h = hashlib.sha256()
    for path in _iter_sdk_files(root):
        rel = path.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def ensure_sdk(*, force: bool = False, install: bool = True) -> Path:
    """Copy package SDK → $Y_AGENT_HOME/ui/.sdk and npm install once.

    Re-materializes when the packaged content digest changes (any file under
    the shipped SDK, not only contract.json version), when the dest is
    incomplete, or when force=True. Preserves node_modules across refreshes.
    """
    dest = sdk_dir()
    src = package_sdk_root()
    ui_dir().mkdir(parents=True, exist_ok=True)

    expected = package_sdk_digest(src)
    marker = dest / _DIGEST_MARKER
    needs_copy = force or not marker.is_file()
    if not needs_copy:
        try:
            if marker.read_text(encoding="utf-8").strip() != expected:
                needs_copy = True
        except OSError:
            needs_copy = True

    # Also refresh if a required shipped file is missing (partial/corrupt dest).
    required = [
        "build.mjs",
        "package.json",
        "theme.css",
        "y-host.d.ts",
        "shims/react.cjs",
        "contract.json",
    ]
    if not needs_copy and any(not (dest / rel).is_file() for rel in required):
        needs_copy = True

    if needs_copy:
        if dest.exists():
            # Keep node_modules across source refreshes when possible.
            node_modules = dest / "node_modules"
            preserved = None
            if node_modules.is_dir() and not force:
                preserved = dest.parent / ".sdk-node_modules.bak"
                if preserved.exists():
                    shutil.rmtree(preserved)
                shutil.move(str(node_modules), str(preserved))
            shutil.rmtree(dest)
            dest.mkdir(parents=True)
            if preserved and preserved.exists():
                shutil.move(str(preserved), str(node_modules))
        _copy_sdk_tree(src, dest)
        marker.write_text(expected + "\n", encoding="utf-8")

    if install:
        _ensure_npm_install(dest)

    return dest


def _iter_sdk_files(root: Path):
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] in _SKIP_TOP:
            continue
        yield path


def _copy_sdk_tree(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for path in _iter_sdk_files(src):
        rel = path.relative_to(src)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _ensure_npm_install(dest: Path) -> None:
    marker = dest / "node_modules" / ".bin" / "tailwindcss"
    esbuild = dest / "node_modules" / ".bin" / "esbuild"
    if marker.is_file() and esbuild.is_file():
        return
    if not shutil.which("npm"):
        raise RuntimeError(
            "npm is required to bootstrap the UI SDK (need @tailwindcss/cli + esbuild)"
        )
    print(f"Installing UI SDK build tools in {dest} …", file=sys.stderr)
    result = subprocess.run(
        ["npm", "install", "--no-fund", "--no-audit"],
        cwd=str(dest),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip() or "npm install failed"
        raise RuntimeError(msg)
