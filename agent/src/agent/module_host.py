"""Host contract for hot-loaded backend modules (todo 3020, phase 3 / D9).

One physical source for the backend half of the module system. Modules may
import from this module and from the pure-function allowlist below. Nothing
else from host packages is contract.

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
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

from sqlalchemy.orm import Session

BACKEND_CONTRACT_VERSION = 1


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
    """Yield a host DB session with the same commit-on-clean-exit contract as get_db()."""
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
