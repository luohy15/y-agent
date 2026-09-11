"""Canonical project identity for publication ownership (todo 3493).

A publication claim is keyed by the repository itself, never by a worktree
path, branch, ref, environment or module slug: two worktrees of the same
repository must contend for the same slot, and the same worktree publishing
two different modules must not obtain two slots.

The canonical form is ``host/owner/repository`` (e.g.
``github.com/luohy15/y-agent``). Only GitHub remotes are normalized
automatically -- the observed repositories are GitHub-hosted, and guessing an
identity for an unknown host (aliases, SSH config hostnames, mirrors) would
silently hand out two slots for one repository. Other hosts need an explicit
identity policy, so they are rejected rather than guessed.
"""

import re

CANONICAL_HOST = "github.com"
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SCP = re.compile(r"^(?P<user>[^@/]+)@(?P<host>[^:/]+):(?P<path>.+)$")
_SCHEME = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<rest>.*)$")

MAX_PROJECT_KEY_LENGTH = 200


class ProjectKeyError(ValueError):
    """A remote/identity that cannot be normalized to a canonical project key."""


def _reject(value: str, reason: str) -> "ProjectKeyError":
    return ProjectKeyError(f"cannot use {value!r} as a project identity: {reason}")


def _split_path(value: str, path: str) -> tuple:
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = [p for p in path.split("/")]
    if len(parts) != 2:
        raise _reject(value, "expected a <owner>/<repository> path")
    owner, repository = parts
    for segment in (owner, repository):
        if not _SEGMENT.match(segment):
            raise _reject(value, f"invalid path segment {segment!r}")
    return owner, repository


def normalize_project_key(value: str) -> str:
    """Return the canonical ``host/owner/repository`` key for a remote.

    Accepts the GitHub forms a checkout's ``origin`` actually carries --
    ``https://github.com/o/r[.git][/]``, ``ssh://git@github.com/o/r.git``, the
    SCP form ``git@github.com:o/r.git`` -- plus an already-canonical
    ``github.com/o/r``. Credentials, query strings, fragments, ports,
    filesystem remotes and non-GitHub hosts raise ``ProjectKeyError``.
    """
    if value is None:
        raise ProjectKeyError("project identity is required")
    raw = value.strip()
    if not raw:
        raise ProjectKeyError("project identity is required")
    if len(raw) > MAX_PROJECT_KEY_LENGTH:
        raise _reject(raw[:60] + "...", "project identity is too long")
    if any(ch.isspace() for ch in raw):
        raise _reject(raw, "whitespace is not allowed")
    if "?" in raw or "#" in raw:
        raise _reject(raw, "query strings and fragments are not allowed")

    scheme_match = _SCHEME.match(raw)
    if scheme_match:
        scheme = scheme_match.group("scheme").lower()
        rest = scheme_match.group("rest")
        if scheme not in ("https", "ssh"):
            raise _reject(raw, f"unsupported scheme {scheme!r}; use https or ssh")
        authority, _, path = rest.partition("/")
        if "@" in authority:
            user, _, authority = authority.rpartition("@")
            # `ssh://git@github.com/...` is the standard SSH form; anything else
            # in the userinfo position is a credential and must not become part
            # of a shared identity.
            if scheme != "ssh" or user != "git":
                raise _reject(raw, "credentials in the remote are not allowed")
        host = authority.lower()
    else:
        scp_match = _SCP.match(raw)
        if scp_match:
            if scp_match.group("user") != "git":
                raise _reject(raw, "credentials in the remote are not allowed")
            host = scp_match.group("host").lower()
            path = scp_match.group("path")
        elif raw.startswith("/") or raw.startswith(".") or raw.startswith("~"):
            raise _reject(raw, "filesystem remotes have no shared identity")
        else:
            host, _, path = raw.partition("/")
            host = host.lower()

    if ":" in host:
        raise _reject(raw, "ports are not allowed in a project identity")
    if host != CANONICAL_HOST:
        raise _reject(
            raw,
            f"only {CANONICAL_HOST} remotes are normalized automatically; "
            "other hosts need an explicit identity policy",
        )

    owner, repository = _split_path(raw, path)
    # GitHub owner/repository names are case-insensitive, so two spellings of
    # one repository must collapse to one key.
    return f"{host}/{owner.lower()}/{repository.lower()}"
