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

The v2 surface adds a narrow bot-config store:
  - bot_config_list / bot_config_get / bot_config_upsert / bot_config_delete /
    bot_config_set_enabled / bot_config_rename
These operate on host-owned BotConfig values only: no repositories, no raw
sessions, no entities, and no generic host-table access. bot_config_rename goes
through the host service so its `chat.bot_name` cascade is preserved.

The v3 surface adds request-bound chat browsing and sharing over host-owned chat
state:
  - chat_list / chat_get / chat_create_share

The v4 surface extends request-bound VM execution with explicit working-directory
and stdin support, and adds a narrow note-path lookup for file rename guards:
  - run_vm_command(..., work_dir=..., stdin=...)
  - note_list_at_path

Every v2/v3/v4 capability is bound to the authenticated request owner, like
run_vm_command, so a module cannot read or overwrite another user's state. These
capabilities are API-request-scoped only: the module CLI half has `cli_user_id()`
but no bound request owner, so it must use the module HTTP API instead.

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
been published against it. The bot-config capability is a genuine surface
addition (todo 3028), so it bumps BACKEND_CONTRACT_VERSION from 1 to 2. The chat
control-plane capability (todo 3042) bumps it from 2 to 3. The file control-plane
capability (todo 3068) extends VM execution with work_dir and stdin and adds
note_list_at_path, bumping it from 3 to 4. Modules declare the minimum version
they use and an older host rejects their bundle. Every later addition to the
surface above bumps the version and, for modules that need it,
`min_backend_version`.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Iterator, Optional

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from storage.dto.bot import BotConfig

BACKEND_CONTRACT_VERSION = 4

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
    work_dir: Optional[str] = None,
    stdin: Optional[str] = None,
) -> str:
    """Run argv on the authenticated owner's VM (local when no api_token, SSH otherwise).

    argv is a list, never a shell string. The host shell-quotes each element
    on the SSH path. The user_id must equal the authenticated request's owner
    (bound by the dispatcher): a caller-chosen different id is rejected, and
    the VM is resolved strictly for that user with no default-user fallback
    (review finding 2). VM config is resolved strictly for the owner with no
    fallback to another user's VM. `work_dir` overrides the configured directory
    when provided; `stdin` is passed without placing bytes in argv. Raises a
    typed error on a non-zero local or SSH exit status (or timeout); callers
    decide how to surface it.
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

    from agent.vm_command import execute_vm_command

    return await execute_vm_command(
        vm_config,
        list(argv),
        stdin=stdin,
        timeout=timeout,
        work_dir=work_dir,
        check=True,
    )


# ---------------------------------------------------------------------------
# v4 file control-plane capability
#
# The file module may ask only which of the authenticated owner's notes block a
# content-key rename. It never receives a note service or generic table access.
# ---------------------------------------------------------------------------


def note_list_at_path(user_id: int, content_key: str) -> list[dict[str, str]]:
    """Return owner-scoped note path blockers as plain dictionaries."""
    owner = _request_owner.get()
    if owner is None or owner != user_id:
        raise ModuleHostAuthError(
            f"note path lookup for user_id={user_id} does not match the "
            f"authenticated request owner (bound={owner}); note access is request-bound"
        )
    from storage.service import note as note_service

    return [
        {"content_key": note.content_key}
        for note in note_service.list_notes_at_path(user_id, content_key)
    ]


# ---------------------------------------------------------------------------
# v2 bot-config capability
#
# A narrow, request-bound store over host-owned BotConfig values (plan-3028).
# The bot module is a hybrid control-plane module: bot_config stays a host
# kernel table (the worker dispatch hot path reads it), so the module manages
# it through this capability instead of importing the host service or
# repository directly. No repositories, raw sessions, entities, or generic
# host-table access are exposed.
# ---------------------------------------------------------------------------


def _require_bot_config_owner(user_id: int) -> None:
    """Refuse a bot-config operation acting for anyone but the request owner.

    Mirrors run_vm_command's review-finding-2 guard: a module must not read or
    overwrite another user's bot configuration (which carries API keys). Only
    the authenticated owner bound by the dispatcher may be passed.
    """
    owner = _request_owner.get()
    if owner is None or owner != user_id:
        raise ModuleHostAuthError(
            f"bot-config operation for user_id={user_id} does not match the "
            f"authenticated request owner (bound={owner}); bot config is request-bound"
        )


def _bot_service(user_id: int):
    """Guard the caller belongs to the request owner, then return the host
    bot-config service. Import is after the guard (like run_vm_command), so a
    rejected call never pays the import."""
    _require_bot_config_owner(user_id)
    from storage.service import bot_config as bot_service

    return bot_service


def bot_config_list(user_id: int) -> list[BotConfig]:
    """All bot-config values owned by `user_id`, as plain BotConfig values."""
    return _bot_service(user_id).list_configs(user_id)


def bot_config_get(user_id: int, name: str = "default") -> Optional[BotConfig]:
    """A single bot-config value by name, or None when the owner has none by that name."""
    return _bot_service(user_id).get_config(user_id, name)


def bot_config_upsert(user_id: int, config: BotConfig) -> BotConfig:
    """Insert or fully replace a bot-config value (keyed by `config.name`).

    The caller composes the full BotConfig it wants persisted; the host
    persists it and returns the same value (matching the host service's
    add_config contract).
    """
    return _bot_service(user_id).add_config(user_id, config)


def bot_config_delete(user_id: int, name: str) -> bool:
    """Delete a bot-config value (except "default"); returns False when it did not exist."""
    return _bot_service(user_id).delete_config(user_id, name)


def bot_config_set_enabled(user_id: int, name: str, enabled: bool) -> bool:
    """Enable or disable a bot-config value; returns False when it did not exist."""
    return _bot_service(user_id).set_enabled(user_id, name, enabled)


def bot_config_rename(user_id: int, old_name: str, new_name: str) -> bool:
    """Rename a bot-config value, preserving the host's `chat.bot_name` cascade.

    Must go through the host service (not a bare repository update) so
    bot_config.ref_bot_name pointers and host-owned chat.bot_name stay in sync.
    """
    return _bot_service(user_id).rename_config(user_id, old_name, new_name)


# ---------------------------------------------------------------------------
# v3 chat control-plane capability
#
# Request-bound browsing and sharing over host-owned chat state. The worker and
# host routes keep owning chat persistence; modules receive plain dictionaries,
# never repositories, sessions, or entities.
# ---------------------------------------------------------------------------


def _require_chat_owner(user_id: int) -> None:
    owner = _request_owner.get()
    if owner is None or owner != user_id:
        raise ModuleHostAuthError(
            f"chat operation for user_id={user_id} does not match the "
            f"authenticated request owner (bound={owner}); chat access is request-bound"
        )


async def chat_list(
    user_id: int,
    *,
    limit: int = 50,
    query: Optional[str] = None,
    offset: int = 0,
    trace_id: Optional[str] = None,
    topic: Optional[str] = None,
    skill: Optional[str] = None,
    tier: Optional[str] = None,
    bot_name: Optional[str] = None,
    status: Optional[str] = None,
    routine_id: Optional[str] = None,
    routine_name: Optional[str] = None,
    routine_only: Optional[bool] = None,
    tag: Optional[str] = None,
    on: Optional[str] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
    created_on: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_on: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
) -> list[dict[str, Any]]:
    """List chats owned by the authenticated request owner as plain dictionaries."""
    _require_chat_owner(user_id)
    from storage.service import chat as chat_service

    chats = await chat_service.list_chats(
        user_id,
        limit=limit,
        query=query,
        offset=offset,
        trace_id=trace_id,
        topic=topic,
        skill=skill,
        tier=tier,
        bot_name=bot_name,
        status=status,
        routine_id=routine_id,
        routine_name=routine_name,
        routine_only=routine_only,
        tag=tag,
        on=on,
        from_=from_,
        to=to,
        created_on=created_on,
        created_from=created_from,
        created_to=created_to,
        updated_on=updated_on,
        updated_from=updated_from,
        updated_to=updated_to,
    )
    return [
        {
            "chat_id": chat.chat_id,
            "title": chat.title,
            "created_at": chat.created_at,
            "updated_at": chat.updated_at,
            "topic": chat.topic,
            "skill": chat.skill,
            "trace_id": chat.trace_id,
            "routine_id": chat.routine_id,
            "routine_name": chat.routine_name,
            "backend": chat.backend,
            "bot_name": chat.bot_name,
            "tier": chat.tier,
            "status": chat.status,
            "unread": chat.unread,
        }
        for chat in chats
    ]


async def chat_get(user_id: int, chat_id: str) -> Optional[dict[str, Any]]:
    """Get one owner-scoped chat's browser content, or None when it is absent."""
    _require_chat_owner(user_id)
    from storage.service import chat as chat_service

    chat = await chat_service.get_chat(user_id, chat_id)
    if chat is None:
        return None
    return {
        "chat_id": chat.id,
        "messages": [message.to_dict() for message in chat.messages],
        "create_time": chat.create_time,
        "update_time": chat.update_time,
    }


async def chat_create_share(
    user_id: int,
    chat_id: str,
    *,
    message_id: Optional[str] = None,
    password: Optional[str] = None,
    generate_password: bool = False,
) -> dict[str, str]:
    """Create an owner-scoped chat share and optionally protect it with a password."""
    _require_chat_owner(user_id)
    from storage import share_password as sp
    from storage.service import chat as chat_service

    generated_password, password_hash = sp.resolve_password(password, generate_password)

    share_id = await chat_service.create_share(
        user_id, chat_id, message_id, password_hash=password_hash
    )
    result = {"share_id": share_id}
    if generated_password is not None:
        result["password"] = generated_password
    return result
