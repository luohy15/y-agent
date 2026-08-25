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

The v5 surface adds request-bound note browsing and authoring over host-owned
note / note_todo_relation state (todo 3071):
  - note_list / note_get / note_create / note_import / note_update / note_delete
  - note_list_by_todo
  - note_relation_create / note_relation_delete
  - note_relations_by_todo / note_relations_by_note
Functions that accept a content_key enforce the home-escape invariant so a
module cannot store a `../`-escaping key regardless of published bytes.

The v10 surface adds fixed configured-maintainer-only API latency monitoring queries:
  - api_latency_summary / api_latency_routes / api_latency_events / api_latency_meta

The v11 surface adds owner-bound tag rename/merge planning and apply:
  - tag_rename_plan / tag_rename_apply

The v12 surface adds configured-maintainer-only provider status reads:
  - provider_status_overview / provider_status_incidents / provider_status_incident /
    provider_status_history

The v13 surface adds owner-bound durable vocabulary creation:
  - tag_create_vocabulary

Every request-bound capability is bound to the authenticated request owner, like
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
note_list_at_path, bumping it from 3 to 4. The note control-plane capability
(todo 3071) adds the eleven owner-bound note_* functions and bumps it from 4
to 5. The three-state chat attention UX (todo 3137) adds `needs_attention` to
`chat_list` row dicts, a surface addition to the existing v3 chat capability,
bumping it from 5 to 6. Chat-list server-side sorting (todo 3152) adds optional
closed `sort_by` / `sort_order` parameters to `chat_list`, bumping it from 6
to 7. The tag control-plane capability (todo 3164) adds owner-bound
`tag_list_vocabulary` / `tag_get` / `tag_add` / `tag_remove` / `tag_backfill`
adapters over `storage.service.tag`, bumping it from 7 to 8. Todo 3169
enriches the existing `tag_get` todo row with `updated_at_unix` (the todo
row's own timestamp) so presentation clients can sort without a second
fetch, bumping it from 8 to 9. API latency monitoring (todo 3211) adds four
fixed configured-maintainer-only query functions over host-owned telemetry state, bumping it
from 9 to 10. Tag rename/merge (todo 3219) adds owner-bound
`tag_rename_plan` / `tag_rename_apply` over coordinated authoring + entity_tag
rewrites, bumping it from 10 to 11. Provider status reads (todo 3266) add four
fixed configured-maintainer-only queries over host-owned external-status data,
bumping it from 11 to 12. Durable canonical tag creation (todo 3290) adds
owner-bound `tag_create_vocabulary`, a normalize-validate-idempotent-create
adapter over `storage.service.tag.create_vocabulary` backed by the new
`tag_vocabulary` table, bumping it from 12 to 13; the tag module raises its
floor to 13 when it publishes the create route. Modules declare the minimum
version they use and an older host rejects their bundle. Every later addition
to the surface above bumps the version and, for modules that need it,
`min_backend_version`.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from storage.dto.bot import BotConfig

BACKEND_CONTRACT_VERSION = 13

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
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> list[dict[str, Any]]:
    """List chats owned by the authenticated request owner as plain dictionaries.

    Optional `sort_by` / `sort_order` (v7) select the closed server-side order:
    sort_by is `updated_at` or `created_at`, sort_order is `asc` or `desc`,
    defaulting to updated_at + desc. Unknown values raise ValueError.
    """
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
        sort_by=sort_by,
        sort_order=sort_order,
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
            "needs_attention": chat.needs_attention,
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


# ---------------------------------------------------------------------------
# v5 note control-plane capability
#
# Request-bound browsing and authoring over host-owned note /
# note_todo_relation state (plan-3071). Share routes, S3 snapshots, and the
# content-path authority stay host-only; modules receive plain dictionaries
# and never repositories, sessions, or entities. content_key writes enforce
# the home-escape invariant here so a module cannot store an escaping key.
# ---------------------------------------------------------------------------


class ModuleHostValidationError(ModuleHostError):
    """A module capability rejected caller input that violates a host invariant."""


def _require_note_owner(user_id: int) -> None:
    owner = _request_owner.get()
    if owner is None or owner != user_id:
        raise ModuleHostAuthError(
            f"note operation for user_id={user_id} does not match the "
            f"authenticated request owner (bound={owner}); note access is request-bound"
        )


def _agent_home() -> Path:
    return Path(os.environ.get("Y_AGENT_HOME", str(Path.home()))).resolve()


def _validate_content_key(content_key: str) -> None:
    """Reject a content_key that escapes Y_AGENT_HOME (todo 3041 / plan-3071 D2)."""
    home = _agent_home()
    path = (home / content_key).resolve()
    if home != path and home not in path.parents:
        raise ModuleHostValidationError("Invalid content key")


def _note_to_dict(note) -> dict[str, Any]:
    return note.to_dict()


def note_list(
    user_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
    include_deleted: bool = False,
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
    """List notes owned by the authenticated request owner as plain dictionaries."""
    _require_note_owner(user_id)
    from storage.service import note as note_service

    notes = note_service.list_notes(
        user_id,
        limit=limit,
        offset=offset,
        include_deleted=include_deleted,
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
    return [_note_to_dict(note) for note in notes]


def note_get(
    user_id: int,
    note_id: str,
    *,
    include_deleted: bool = False,
) -> Optional[dict[str, Any]]:
    """Get one owner-scoped note, or None when it is absent."""
    _require_note_owner(user_id)
    from storage.service import note as note_service

    note = note_service.get_note(user_id, note_id, include_deleted=include_deleted)
    if note is None:
        return None
    return _note_to_dict(note)


def note_create(
    user_id: int,
    content_key: str,
    *,
    front_matter: Optional[Dict] = None,
) -> dict[str, Any]:
    """Create an owner-scoped note; rejects a home-escaping content_key."""
    _require_note_owner(user_id)
    _validate_content_key(content_key)
    from storage.service import note as note_service

    return _note_to_dict(note_service.create_note(user_id, content_key, front_matter=front_matter))


def note_import(
    user_id: int,
    content_key: str,
    *,
    front_matter: Optional[Dict] = None,
) -> dict[str, Any]:
    """Import or refresh an owner-scoped note by content_key."""
    _require_note_owner(user_id)
    _validate_content_key(content_key)
    from storage.service import note as note_service

    return _note_to_dict(note_service.import_note(user_id, content_key, front_matter=front_matter))


def note_update(
    user_id: int,
    note_id: str,
    *,
    content_key: Optional[str] = None,
    front_matter: Optional[Dict] = None,
) -> Optional[dict[str, Any]]:
    """Update an owner-scoped note; rejects a home-escaping content_key when provided."""
    _require_note_owner(user_id)
    if content_key is not None:
        _validate_content_key(content_key)
    from storage.service import note as note_service

    note = note_service.update_note(
        user_id, note_id, content_key=content_key, front_matter=front_matter
    )
    if note is None:
        return None
    return _note_to_dict(note)


def note_delete(
    user_id: int,
    note_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Soft-delete an owner-scoped note; returns the host service's structured result.

    Callers map `{ok: False, ...}` to HTTP 409 themselves. The capability never
    raises for a guarded delete: the relation counts are the module's response body.
    """
    _require_note_owner(user_id)
    from storage.service import note as note_service

    return note_service.delete_note(user_id, note_id, force=force)


def note_list_by_todo(
    user_id: int,
    todo_id: str,
    *,
    include_deleted: bool = False,
) -> list[dict[str, Any]]:
    """List owner-scoped notes linked to a todo as plain dictionaries."""
    _require_note_owner(user_id)
    from storage.service import note as note_service
    from storage.service import note_todo_relation as relation_service

    note_ids = relation_service.list_by_todo(user_id, todo_id)
    if not note_ids:
        return []
    notes = note_service.get_notes_by_ids(
        user_id, note_ids, include_deleted=include_deleted
    )
    return [_note_to_dict(note) for note in notes]


def note_relation_create(user_id: int, note_id: str, todo_id: str) -> bool:
    """Create an owner-scoped note↔todo relation; returns True when newly created."""
    _require_note_owner(user_id)
    from storage.service import note_todo_relation as relation_service

    return relation_service.create_relation(user_id, note_id, todo_id)


def note_relation_delete(user_id: int, note_id: str, todo_id: str) -> bool:
    """Delete an owner-scoped note↔todo relation; returns True when a row was removed."""
    _require_note_owner(user_id)
    from storage.service import note_todo_relation as relation_service

    return relation_service.delete_relation(user_id, note_id, todo_id)


def note_relations_by_todo(user_id: int, todo_id: str) -> list[str]:
    """Return the owner-scoped note_ids linked to a todo."""
    _require_note_owner(user_id)
    from storage.service import note_todo_relation as relation_service

    return list(relation_service.list_by_todo(user_id, todo_id))


def note_relations_by_note(user_id: int, note_id: str) -> list[str]:
    """Return the owner-scoped todo_ids linked to a note."""
    _require_note_owner(user_id)
    from storage.service import note_todo_relation as relation_service

    return list(relation_service.list_by_note(user_id, note_id))


# ---------------------------------------------------------------------------
# v8 tag control-plane capability (v9 enriches tag_get todo rows)
#
# Request-bound vocabulary, lookup, generic projection writes, and authoring-
# surface backfill over host-owned entity_tag state (plan-3164). The kernel
# keeps normalization, resolvers, hydration, and carrier filters; modules only
# receive plain JSON-safe dictionaries and never repositories or sessions.
# v9 (todo 3169) adds `updated_at_unix` on hydrated todo rows from tag_get so
# the tag module can sort by recency without imposing host display policy.
# ---------------------------------------------------------------------------


def _require_tag_owner(user_id: int) -> None:
    owner = _request_owner.get()
    if owner is None or owner != user_id:
        raise ModuleHostAuthError(
            f"tag operation for user_id={user_id} does not match the "
            f"authenticated request owner (bound={owner}); tag access is request-bound"
        )


def tag_list_vocabulary(user_id: int) -> list[dict[str, Any]]:
    """Owner-scoped vocabulary rows with usage counts as plain dictionaries.

    A durably created but never-attached tag (todo 3290) appears here with
    count 0, so this is no longer just distinct entity_tag values.
    """
    _require_tag_owner(user_id)
    from storage.service import tag as tag_service

    return [
        {"tag": tag, "count": count}
        for tag, count in tag_service.list_vocabulary(user_id)
    ]


def tag_get(
    user_id: int,
    tag: str,
    *,
    prefix: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Hydrated owner-scoped tag lookup grouped by entity_type."""
    _require_tag_owner(user_id)
    from storage.service import tag as tag_service

    return tag_service.get_by_tag(user_id, tag, prefix=prefix)


def tag_add(
    user_id: int,
    entity_type: str,
    entity_id: str,
    tags: List[str],
) -> dict[str, list[str]]:
    """Add projection tags for one owner-scoped entity; email entity IDs are thread keys."""
    _require_tag_owner(user_id)
    from storage.service import tag as tag_service

    added = [
        tag
        for tag in tags
        if tag_service.add_tag(user_id, entity_type, entity_id, tag)
    ]
    return {"added": added}


def tag_remove(
    user_id: int,
    entity_type: str,
    entity_id: str,
    tags: List[str],
) -> dict[str, list[str]]:
    """Remove projection tags for one owner-scoped entity; email entity IDs are thread keys."""
    _require_tag_owner(user_id)
    from storage.service import tag as tag_service

    removed = [
        tag
        for tag in tags
        if tag_service.remove_tag(user_id, entity_type, entity_id, tag)
    ]
    return {"removed": removed}


def tag_backfill(
    user_id: int,
    *,
    dry_run: bool = False,
    entity_types: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Project pre-existing note/entity/todo authoring tags into entity_tag.

    The storage service envelope includes the internal integer user_id; strip it
    so the capability (and any module API that forwards it) never exposes a
    private DB identifier across the host boundary.
    """
    _require_tag_owner(user_id)
    from storage.service import tag as tag_service

    result = tag_service.backfill_tags(
        user_id,
        dry_run=dry_run,
        entity_types=entity_types,
        limit=limit,
    )
    return {
        "dry_run": result["dry_run"],
        "by_type": result["by_type"],
        "total_synced": result["total_synced"],
        "total_tag_rows": result["total_tag_rows"],
    }


# ---------------------------------------------------------------------------
# v11 tag rename/merge capability (todo 3219)
#
# Owner-bound plan + apply over coordinated authoring-field and entity_tag
# rewrites. The host owns the DB half; the module CLI owns on-disk front matter
# and confirmation. plan_hash is the fail-closed drift gate: the CLI echoes the
# hash from plan, and apply refuses on mismatch (409).
# ---------------------------------------------------------------------------


def tag_rename_plan(user_id: int, source: str, target: str) -> dict[str, Any]:
    """Compute an owner-scoped rename/merge plan; does not mutate."""
    _require_tag_owner(user_id)
    from storage.service import tag as tag_service

    return tag_service.plan_rename(user_id, source, target)


def tag_rename_apply(
    user_id: int,
    source: str,
    target: str,
    *,
    plan_hash: str,
) -> dict[str, Any]:
    """Apply an owner-scoped rename/merge; refuses on plan_hash mismatch."""
    _require_tag_owner(user_id)
    from storage.service import tag as tag_service

    return tag_service.apply_rename(
        user_id, source, target, plan_hash=plan_hash
    )


# ---------------------------------------------------------------------------
# v10 API latency monitoring capability
#
# The host owns request-bound capture and maintenance of its telemetry tables.
# Monitor receives only these fixed JSON-safe queries, never a session or a
# generic metrics/SQL interface.
# ---------------------------------------------------------------------------


def _api_latency_service(user_id: int):
    owner = _request_owner.get()
    if owner is None or owner != user_id:
        raise ModuleHostAuthError(
            f"API latency operation for user_id={user_id} does not match the "
            f"authenticated request owner (bound={owner}); monitoring is request-bound"
        )
    from storage.service.user import get_module_maintainer_user_id

    maintainer_id = get_module_maintainer_user_id()
    if maintainer_id is None or owner != maintainer_id:
        raise ModuleHostAuthError(
            "API latency monitoring is restricted to the configured module maintainer"
        )
    from storage.service import api_latency as latency_service

    return latency_service


def api_latency_summary(
    user_id: int,
    range_name: str = "24h",
    *,
    route: Optional[str] = None,
    method: Optional[str] = None,
    status_class: Optional[str] = None,
    completion: Optional[str] = None,
    module_slug: Optional[str] = None,
) -> dict[str, Any]:
    """Summary, exact/merged percentiles, and series for one closed range."""
    return _api_latency_service(user_id).summary(
        range_name,
        route=route,
        method=method,
        status_class=status_class,
        completion=completion,
        module_slug=module_slug,
    )


def api_latency_routes(
    user_id: int,
    range_name: str = "24h",
    *,
    min_samples: int = 20,
    limit: int = 50,
    method: Optional[str] = None,
    status_class: Optional[str] = None,
    completion: Optional[str] = None,
    module_slug: Optional[str] = None,
) -> dict[str, Any]:
    """Bounded route ranking for one closed range and allowlisted filters."""
    return _api_latency_service(user_id).routes(
        range_name,
        min_samples=min_samples,
        limit=limit,
        method=method,
        status_class=status_class,
        completion=completion,
        module_slug=module_slug,
    )


def api_latency_events(
    user_id: int,
    range_name: str = "24h",
    *,
    route: Optional[str] = None,
    order: str = "recent",
    limit: int = 100,
    method: Optional[str] = None,
    status_class: Optional[str] = None,
    completion: Optional[str] = None,
    module_slug: Optional[str] = None,
) -> dict[str, Any]:
    """At most 100 sparse raw rows, only for raw-backed ranges."""
    return _api_latency_service(user_id).events(
        range_name,
        route=route,
        order=order,
        limit=limit,
        method=method,
        status_class=status_class,
        completion=completion,
        module_slug=module_slug,
    )


def api_latency_meta(user_id: int) -> dict[str, Any]:
    """Collection bounds, row volume, route cardinality, and rollup freshness."""
    return _api_latency_service(user_id).meta()


# ---------------------------------------------------------------------------
# v12 provider status capability
# ---------------------------------------------------------------------------


def _provider_status_service(user_id: int):
    owner = _request_owner.get()
    if owner is None or owner != user_id:
        raise ModuleHostAuthError(
            f"provider status operation for user_id={user_id} does not match the "
            f"authenticated request owner (bound={owner}); provider status is request-bound"
        )
    from storage.service.user import get_module_maintainer_user_id

    maintainer_id = get_module_maintainer_user_id()
    if maintainer_id is None or owner != maintainer_id:
        raise ModuleHostAuthError(
            "provider status is restricted to the configured module maintainer"
        )
    from storage.service import provider_status as status_service

    return status_service


def provider_status_overview(user_id: int, provider: str = "anthropic") -> dict[str, Any]:
    """Provider-reported current health and channel freshness for Anthropic only."""
    return _provider_status_service(user_id).overview(provider)


def provider_status_incidents(
    user_id: int,
    provider: str,
    start,
    end,
    *,
    limit: int = 100,
) -> dict[str, Any]:
    """Bounded incident list for one explicit time range."""
    return _provider_status_service(user_id).incidents(provider, start, end, limit)


def provider_status_incident(user_id: int, provider: str, source_id: str) -> dict[str, Any]:
    """One incident and its bounded normalized update timeline."""
    return _provider_status_service(user_id).incident(provider, source_id)


def provider_status_history(
    user_id: int,
    provider: str,
    start,
    end,
    *,
    limit: int = 500,
) -> dict[str, Any]:
    """Bounded component transition history for one explicit time range."""
    return _provider_status_service(user_id).history(provider, start, end, limit)


# ---------------------------------------------------------------------------
# v13 tag vocabulary-creation capability (todo 3290)
#
# Owner-bound durable registration of a canonical tag that can exist with zero
# entity_tag uses. The host owns normalization, syntax validation, and the
# idempotent/race-safe create; the module only forwards raw input and renders
# the returned canonical spelling.
# ---------------------------------------------------------------------------


def tag_create_vocabulary(user_id: int, tag: str) -> dict[str, Any]:
    """Normalize, validate, and idempotently register a canonical vocabulary tag.

    Returns {"tag": canonical, "created": bool}. Raises ValueError (a
    storage.service.tag.TagVocabularyError) on blank or syntactically invalid
    input; callers map that to HTTP 400.
    """
    _require_tag_owner(user_id)
    from storage.service import tag as tag_service

    return tag_service.create_vocabulary(user_id, tag)
