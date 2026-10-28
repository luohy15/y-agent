"""Fail-closed check that a publish matches the live origin/main tip.

Remote truth is `git ls-remote` (read-only, does not move refs). The stale
local `origin/main` is never consulted. When the tip commit is not already
local, it is downloaded with `git fetch --refmap=` so `merge-base` can tell
behind from diverged without writing branches, remote-tracking refs, or
FETCH_HEAD.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

import click

from storage.service.module_icon import normalize_module_icon

from . import _paths

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_COMPONENTS = {".build", "__pycache__", "tests", "node_modules", ".pytest_cache"}
_GIT_TIMEOUT = 30


def verify_source_snapshot(slug: str, expected_sha: str) -> str:
    """Return the live tip when HEAD, the tip and expected_sha are the same clean tree.

    Raises click.ClickException otherwise. Reads modules_dir() at call time.
    """
    if not isinstance(expected_sha, str) or not _SHA_RE.fullmatch(expected_sha):
        raise click.ClickException(
            "--source-sha must be the full 40-hex lowercase SHA of origin/main"
        )
    root = _paths.modules_dir()
    tip = _live_tip(root)
    if expected_sha != tip:
        raise click.ClickException(
            f"refusing publish: tip mismatch: --source-sha {expected_sha} "
            f"is not the live origin/main tip {tip}"
        )
    head = _git_out(root, "rev-parse", "HEAD")
    if head != tip:
        _ensure_commit(root, tip)
        _refuse_relation(root, head, tip)
    _refuse_dirty(root, slug)
    return tip


def _live_tip(root) -> str:
    try:
        proc = _run(root, ["ls-remote", "origin", "refs/heads/main"])
    except subprocess.TimeoutExpired as exc:
        raise click.ClickException(
            "remote verification failed: timed out reading origin refs/heads/main"
        ) from exc
    if proc.returncode != 0 or not proc.stdout.strip():
        detail = (proc.stderr or proc.stdout or "no output").strip().splitlines()
        tail = detail[-1] if detail else "no output"
        raise click.ClickException(f"remote verification failed: {tail}")
    for line in proc.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        if ref == "refs/heads/main" and _SHA_RE.fullmatch(sha):
            return sha
    raise click.ClickException(
        "remote verification failed: origin refs/heads/main did not return a SHA"
    )


def _ensure_commit(root, sha: str) -> None:
    if _run(root, ["cat-file", "-e", f"{sha}^{{commit}}"]).returncode == 0:
        return
    try:
        fetched = _run(
            root,
            [
                "fetch",
                "--refmap=",
                "--no-tags",
                "--no-write-fetch-head",
                "origin",
                "refs/heads/main",
            ],
        )
    except subprocess.TimeoutExpired as exc:
        raise click.ClickException(
            "remote verification failed: timed out downloading origin/main"
        ) from exc
    if fetched.returncode != 0 or _run(root, ["cat-file", "-e", f"{sha}^{{commit}}"]).returncode != 0:
        raise click.ClickException(
            "remote verification failed: could not read origin/main for comparison"
        )


def _refuse_relation(root, head: str, tip: str) -> None:
    head_is_ancestor = _is_ancestor(root, head, tip)
    tip_is_ancestor = _is_ancestor(root, tip, head)
    if tip_is_ancestor and not head_is_ancestor:
        raise click.ClickException(
            f"refusing publish: HEAD {head} is ahead of origin/main {tip}; "
            "this command does not push"
        )
    if head_is_ancestor and not tip_is_ancestor:
        raise click.ClickException(
            f"refusing publish: HEAD {head} is behind origin/main {tip}; "
            "this command does not update branches or reset the checkout"
        )
    raise click.ClickException(
        f"refusing publish: HEAD {head} has diverged from origin/main {tip}"
    )


def _is_ancestor(root, ancestor: str, descendant: str) -> bool:
    proc = _run(root, ["merge-base", "--is-ancestor", ancestor, descendant])
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    raise click.ClickException(
        "remote verification failed: could not compare HEAD with origin/main"
    )


def _refuse_dirty(root, slug: str) -> None:
    proc = _run(
        root,
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignored=matching",
            "--",
            f"{slug}/",
            "common/",
            "shared/",
        ],
    )
    if proc.returncode != 0:
        raise click.ClickException("refusing publish: could not check build-input cleanliness")
    bad = [path for path in _status_paths(proc.stdout) if not _allowed(path)]
    if bad:
        raise click.ClickException(
            "refusing publish: dirty build inputs: " + ", ".join(bad[:20])
        )
    # git status reports a clean symlink as clean. The API zip follows file
    # symlinks (os.walk + is_file + read_bytes), so a link can pull bytes that
    # are not in the approved commit. Refuse those links before building.
    links = _build_input_symlinks(root, slug)
    if links:
        raise click.ClickException(
            "refusing publish: symlink in build inputs: " + ", ".join(links[:20])
        )


def _build_input_symlinks(root, slug: str) -> list[str]:
    """Symlinks the API zip or the UI build would follow.

    Skips the same generated noise cleanliness allows. Does not follow links:
    a linked directory is itself an entry, and its children are not walked.
    """
    found: list[str] = []
    for base in (slug, "common", "shared"):
        start = root / base
        # os.walk follows a symlink given as its start even with followlinks=False.
        if start.is_symlink():
            found.append(base)
            continue
        if not start.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
            dirnames[:] = [
                name for name in dirnames
                if not _allowed(_rel(root, Path(dirpath) / name))
            ]
            for name in list(dirnames) + filenames:
                path = Path(dirpath) / name
                if path.is_symlink() and not _allowed(_rel(root, path)):
                    found.append(_rel(root, path))
            dirnames[:] = [name for name in dirnames if not (Path(dirpath) / name).is_symlink()]
    return sorted(found)


def _rel(root, path) -> str:
    return path.relative_to(root).as_posix()


def _allowed(path: str) -> bool:
    if path.endswith(".pyc") or path.endswith(".pyo"):
        return True
    return any(part in _ALLOWED_COMPONENTS for part in PurePosixPath(path).parts)


def _status_paths(stdout: str) -> list[str]:
    parts = stdout.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(parts):
        record = parts[index]
        if record == "" or len(record) < 4:
            index += 1
            continue
        status = record[:2]
        paths.append(record[3:])
        index += 1
        if "R" in status or "C" in status:
            if index < len(parts) and parts[index] != "":
                paths.append(parts[index])
                index += 1
    return paths


def _git_out(root, *args: str) -> str:
    proc = _run(root, list(args))
    if proc.returncode != 0 or not proc.stdout.strip():
        raise click.ClickException(f"refusing publish: git {' '.join(args)} failed")
    return proc.stdout.strip()


def find_icon_conflict(slug: str, resolved_icon: str, root=None) -> str | None:
    """Return the other module under ``root`` that already holds this icon.

    ``root`` defaults to the canonical module source root. A registry key is
    compared as a string. SVG markup is compared after ``normalize_module_icon``.
    Directories without ``module.json``, this slug, and siblings whose icon
    cannot be read are skipped. A broken sibling icon is not an error.
    """
    base = Path(root) if root is not None else _paths.modules_dir()
    if not base.is_dir() or not isinstance(resolved_icon, str) or resolved_icon == "":
        return None
    for child in sorted(base.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or child.name == slug:
            continue
        meta_path = child / "module.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            raw = meta.get("icon") if isinstance(meta, dict) else None
            sibling = _resolved_sibling_icon(child, raw)
        except (OSError, ValueError, json.JSONDecodeError, click.ClickException):
            continue
        if sibling == resolved_icon:
            return child.name
    return None


def _resolved_sibling_icon(module_dir: Path, raw) -> str:
    if not isinstance(raw, str) or raw == "":
        raise ValueError("empty icon")
    if raw.endswith(".svg"):
        rel = Path(raw)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"module icon SVG must be a relative path under ui/, got {raw!r}")
        ui = (module_dir / "ui").resolve()
        full = (module_dir.resolve() / rel).resolve()
        full.relative_to(ui)
        if not full.is_file():
            raise ValueError(f"module icon SVG not found: {raw}")
        return normalize_module_icon(full.read_text(encoding="utf-8"))
    if raw.lstrip().startswith("<"):
        return normalize_module_icon(raw)
    return raw


def _run(root, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
    )
