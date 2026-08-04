"""Host contract for hot-loaded backend modules (todo 3020, phase 3 / D9).

One physical source for the backend half of the module system. Modules may
import from this module and from the pure-function allowlist below. Nothing
else from host packages is contract.

The v1 surface a module may import from here:
  - BACKEND_CONTRACT_VERSION      the host's own contract version (see below)
  - session()                     DB session with get_db() transaction semantics
  - run_vm_command()              argv on the authenticated owner's VM
  - cli_user_id()                 acting user for the CLI half (`y <slug> …`),
                                  the counterpart of `request.state.user_id`
  - EXTERNAL_TABLE_INFO_KEY       Table.info marker for a referenced-but-not-owned
                                  host kernel table (D4), read by host tooling
                                  via is_external_table() / owned_tables()

is_external_table() / owned_tables() are host tooling (publish preflight,
`y module schema-sql`), so the marker is interpreted in exactly one place; a
module only ever needs the constant.

Allowlist (pure functions, no DB, no entity, no repository):
  - storage.service.time_range  (parse_time_range, TIME_RANGE_ALIASES)
  - storage.util timestamp helpers
    (get_utc_iso8601_timestamp, get_unix_timestamp, local_today)

Explicit non-list (modules must not reach for these):
  - agent.tool_base.Tool or any Tool subclass
  - paramiko / boto3 objects or credentials
  - raw SQLAlchemy Engine / SessionLocal
  - any host repository or service other than the allowlist above
  - worker internals

Paramiko/boto3 imports stay inside run_vm_command so importing this module
stays cheap on the `y` hot path.

Contract version: cli_user_id and the external-table protocol are part of v1,
not a v2 bump, because v1 has never shipped — no host carrying
BACKEND_CONTRACT_VERSION has been deployed and no backend module version has
been published against it. Every later addition to the surface above bumps the
version and, for modules that need it, `min_backend_version`.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

from sqlalchemy.orm import Session

BACKEND_CONTRACT_VERSION = 1

# Table.info key marking a table a module *references* but does not own — the
# host kernel tables its foreign keys point at (D4 allows `user_id -> user.id`).
# A module must declare such a table in its own MetaData or SQLAlchemy cannot
# resolve the ForeignKey (sorted_tables / CreateTable both raise), but the host
# tooling that reads `<pkg>.entities.metadata` (publish preflight,
# `y module schema-sql`) skips it: the module neither owns its schema nor may
# create it.
EXTERNAL_TABLE_INFO_KEY = "module_external"


def is_external_table(table) -> bool:
    """True when `table` is a reference stub for a table the module does not own."""
    return bool((table.info or {}).get(EXTERNAL_TABLE_INFO_KEY))


def owned_tables(metadata):
    """The tables a module actually owns, in dependency order."""
    return [table for table in metadata.sorted_tables if not is_external_table(table)]


def cli_user_id() -> int:
    """The resolved acting user for the CLI half of a module (`y <slug> …`).

    The API half reads `request.state.user_id`; the CLI half has no request, so
    the host resolves the same identity from `Y_USER_ID` / the default account.
    Kept here so module CLI code never imports a host service directly.
    """
    from storage.service.user import get_cli_user_id

    return get_cli_user_id()


class ModuleHostError(Exception):
    """Base class for host-capability failures surfaced to module code."""


class ModuleHostAuthError(ModuleHostError):
    """run_vm_command was asked to act for a user other than the authenticated
    request's owner. Module code must never steer VM execution at an arbitrary
    user-chosen identity (review finding 2)."""


class ModuleVmNotConfiguredError(ModuleHostError):
    """The authenticated owner has no VM configured, so a VM command cannot run.
    There is deliberately NO fallback to another (e.g. the global default)
    user's VM: falling back would hand that account command execution on it."""


# The user_id owning the in-flight authenticated module request. Set by the
# dispatcher for the duration of a backend-module request; run_vm_command reads
# it so a caller-chosen user_id can never pick a different owner's VM.
_request_owner: ContextVar[Optional[int]] = ContextVar(
    "module_request_owner", default=None
)


def bind_request_owner(user_id: int):
    """Bind the authenticated owner for the current request; returns the token
    to pass to reset_request_owner. Run within a request to context-vars so
    handler tasks spawned by FastAPI inherit it."""
    return _request_owner.set(user_id)


def reset_request_owner(token) -> None:
    _request_owner.reset(token)


@contextmanager
def request_owner(user_id: int) -> Iterator[None]:
    token = bind_request_owner(user_id)
    try:
        yield
    finally:
        reset_request_owner(token)


@contextmanager
def session() -> Iterator[Session]:
    """Yield a host DB session with the same commit-on-clean-exit contract as get_db().

    Nested use inside an already-open session is *not* a savepoint: each call
    opens its own session and commits on clean exit, exactly like get_db().
    """
    from storage.database.base import get_db

    with get_db() as db:
        yield db


async def run_vm_command(
    user_id: int,
    vm_name: Optional[str],
    argv: list[str],
    *,
    timeout: float = 30,
) -> str:
    """Run argv on the authenticated owner's VM (local when no api_token, SSH otherwise).

    argv is a list, never a shell string. The host shell-quotes each element
    on the SSH path. The user_id must equal the authenticated request's owner
    (bound by the dispatcher): a caller-chosen different id is rejected, and
    the VM is resolved strictly for that user with no default-user fallback
    (review finding 2). VM config is resolved strictly for the owner with no
    fallback to another user's VM. Raises a typed error on a non-zero local or
    SSH exit status (or timeout); callers decide how to surface it.
    """
    if not argv:
        raise ValueError("argv must be a non-empty list")
    if not all(isinstance(part, str) for part in argv):
        raise TypeError("argv elements must be strings")

    owner = _request_owner.get()
    if owner is None or owner != user_id:
        raise ModuleHostAuthError(
            f"run_vm_command user_id={user_id} does not match the authenticated "
            f"request owner (bound={owner}); VM execution is request-bound"
        )

    # Lazy: keeps paramiko/boto3/cryptography off the import path of this module.
    from storage.service import vm_config as vm_service

    vm_config = vm_service.get_config(user_id, vm_name or "default")
    if vm_config is None:
        raise ModuleVmNotConfiguredError(
            f"no VM configured for owner {user_id} (vm={vm_name or 'default'})"
        )

    cmd = list(argv)
    if not vm_config.api_token:
        from agent.tools.local_exec import local_exec

        return await local_exec(cmd, None, timeout=timeout, cwd=vm_config.work_dir or None, check=True)
    from agent.tools.ssh_exec import ssh_exec

    return await ssh_exec(
        vm_config, cmd, None, dir=vm_config.work_dir or None, timeout=timeout, check=True
    )
