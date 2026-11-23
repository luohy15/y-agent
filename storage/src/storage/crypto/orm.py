"""Seal classified columns on flush and open them on load. No tenant key means a no-op."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, object_session
from sqlalchemy.orm.attributes import set_committed_value

from storage.crypto.fields import SPECS
from storage.crypto.tenant import (
    TenantCryptoError,
    blind_index,
    key_state,
    open_stored,
    seal,
)

_INSTALLED = False
_RESTORE = "tenant_crypto_restore"


@lru_cache(maxsize=1)
def _set_write_columns() -> dict[str, frozenset[str]]:
    columns = {}
    for name, spec in SPECS.items():
        names = set(spec.fields + spec.clear + tuple(item[1] for item in spec.bidx) + ("enc_version",))
        mapper = inspect(_model(name))
        # ORM attribute names can differ from the physical UPDATE column keys.
        physical = {column.key for name in names for column in mapper.attrs[name].columns}
        columns[spec.table] = frozenset(names | physical)
    return columns


def classified_set_write(statement, parameters=None) -> bool:
    """Recognize UPDATE assignments that would bypass per-row sealing."""
    if not getattr(statement, "is_update", False):
        return False
    sensitive = _set_write_columns().get(statement.table.name, frozenset())
    if not sensitive:
        return False
    columns = set()
    for key in (statement._values or {}):
        columns.add(key if isinstance(key, str) else key.key)
    for key, _value in (statement._ordered_values or ()):
        columns.add(key if isinstance(key, str) else key.key)
    # Session.execute(update(Model), mappings) supplies assignments separately.
    batches = parameters if isinstance(parameters, (list, tuple)) else (parameters,)
    for batch in batches:
        if batch:
            columns.update(batch)
    return bool(columns & sensitive)


def _guard_set_write(execute_state) -> None:
    if execute_state.is_update and classified_set_write(execute_state.statement, execute_state.parameters):
        raise TenantCryptoError("tenant_crypto_set_write")


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    event.listen(Session, "do_orm_execute", _guard_set_write)
    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "after_flush", _after_flush)
    event.listen(Session, "after_rollback", _after_rollback)
    for name in SPECS:
        model = _model(name)
        event.listen(model, "load", _on_load, restore_load_context=True)
        event.listen(model, "refresh", _on_refresh, restore_load_context=True)


def _model(name: str):
    import storage.entity.bot_config as bot_config
    import storage.entity.calendar_event as calendar_event
    import storage.entity.chat as chat
    import storage.entity.chat_context as chat_context
    import storage.entity.chat_wakeup as chat_wakeup
    import storage.entity.email as email
    import storage.entity.email_account as email_account
    import storage.entity.english_correction as english_correction
    import storage.entity.entity as entity
    import storage.entity.entity_tag as entity_tag
    import storage.entity.link as link
    import storage.entity.mcp as mcp
    import storage.entity.note as note
    import storage.entity.relay_credential as relay_credential
    import storage.entity.reminder as reminder
    import storage.entity.routine as routine
    import storage.entity.rss_feed as rss_feed
    import storage.entity.tag_vocabulary as tag_vocabulary
    import storage.entity.todo as todo
    import storage.entity.upload_job as upload_job
    import storage.entity.user_cookies as user_cookies
    import storage.entity.user_preference as user_preference
    import storage.entity.vm_config as vm_config
    import storage.entity.wechat as wechat

    modules = (
        wechat, chat, chat_wakeup, todo, entity_tag, tag_vocabulary, calendar_event, reminder,
        routine, email, email_account, english_correction, entity, note, link, rss_feed,
        bot_config, vm_config, user_cookies, user_preference, upload_job, chat_context, mcp,
        relay_credential,
    )
    for module in modules:
        if hasattr(module, name):
            return getattr(module, name)
    raise RuntimeError(f"missing entity {name}")


def _owner(obj, session, spec) -> int | None:
    if spec.credential_owner:
        from storage.entity.mcp import McpConnectorEntity

        connector = session.query(McpConnectorEntity).filter_by(id=obj.connector_pk).one_or_none()
        return None if connector is None else connector.user_id
    if spec.owner_attr is None:
        return None
    return getattr(obj, spec.owner_attr, None)


def _public_id(obj, spec, bidx_values: dict[str, str]) -> str:
    try:
        return spec.public_id(obj, bidx_values)
    except Exception as exc:
        raise TenantCryptoError("encryption_row_id_missing") from exc


def column_values(fetched, count: int) -> tuple:
    """One column comes back as a Row, not a scalar. Never assign that Row."""
    if count == 1:
        return (fetched[0],)
    return tuple(fetched)


def _hydrate_unloaded(obj, spec, owner: int) -> None:
    """Load raiseload/deferred classified columns without touching their loader.

    A list query defers ``history`` with raiseload. Reading it raises. Fetch the
    stored value, and open it when this row is already an envelope, so a later
    seal does not wrap ciphertext or leave a plaintext column on an encrypted row.
    """
    missing = [name for name in spec.fields if name in inspect(obj).unloaded]
    if not missing:
        return
    state = inspect(obj)
    session = object_session(obj)
    if session is None or state.identity is None:
        return
    columns = [getattr(type(obj), name) for name in missing]
    fetched = session.query(*columns).filter(state.mapper.primary_key[0] == state.identity[0]).one()
    values = column_values(fetched, len(missing))
    version = int(getattr(obj, "enc_version", 0) or 0)
    public_id = None
    if version == 1:
        bidx_values = {}
        for source, bidx_name, _purpose in spec.bidx:
            if bidx_name in inspect(obj).unloaded:
                continue
            token = getattr(obj, bidx_name, None)
            if token:
                bidx_values[source] = token
        public_id = _public_id(obj, spec, bidx_values)
    for name, value in zip(missing, values, strict=True):
        if version == 1 and value is not None:
            value = open_stored(
                session, user_id=owner, table=spec.table, column=name, public_id=public_id, value=value,
            )
        setattr(obj, name, value)


def apply_tenant_write(obj, state, owner: int):
    """Seal one row, or leave a keyless legacy row untouched. Returns plaintext to restore."""
    spec = SPECS.get(type(obj).__name__)
    if spec is None or state is None or state.kind == "none":
        return None
    if state.kind == "retired":
        raise TenantCryptoError("tenant_key_retired")
    _hydrate_unloaded(obj, spec, owner)
    unloaded = {name for name in spec.fields if name in inspect(obj).unloaded}
    # Pending inserts leave unset classified columns out of the dict. Only a
    # persistent row may bail out; a new row still seals the values it has.
    if inspect(obj).identity is not None and unloaded and int(getattr(obj, "enc_version", 0) or 0) != 1:
        return None
    if state.kind == "disabled":
        if (getattr(obj, "enc_version", 0) or 0) == 1:
            for _name, bidx_name, _purpose in spec.bidx:
                if hasattr(obj, bidx_name):
                    setattr(obj, bidx_name, None)
            obj.enc_version = 0
        return None
    plain = {name: getattr(obj, name) for name in spec.fields if name not in unloaded}
    bidx_values = {}
    for source, bidx_name, purpose in spec.bidx:
        source_value = plain.get(source, getattr(obj, source, None))
        if source_value is None:
            setattr(obj, bidx_name, None)
            continue
        token = blind_index(state.active.bidx, purpose, str(source_value))
        setattr(obj, bidx_name, token)
        bidx_values[source] = token
    public_id = _public_id(obj, spec, bidx_values)
    try:
        for name, value in plain.items():
            if value is None:
                continue
            setattr(obj, name, seal(
                state.active.dek, user_id=int(owner), table=spec.table, column=name,
                public_id=public_id, value=value, key_id=state.active.key_id,
            ))
        for name in spec.clear:
            setattr(obj, name, None)
        obj.enc_version = 1
    except Exception:
        for name, value in plain.items():
            setattr(obj, name, value)
        raise
    return plain


def _before_flush(session, flush_context, instances) -> None:
    pending = list(session.new) + list(session.dirty)
    restores = session.info.setdefault(_RESTORE, [])
    for obj in pending:
        spec = SPECS.get(type(obj).__name__)
        if spec is None:
            continue
        with session.no_autoflush:
            owner = _owner(obj, session, spec)
            state = key_state(session, owner) if owner is not None else None
        if owner is None or state is None:
            continue
        plain = apply_tenant_write(obj, state, int(owner))
        if plain is not None:
            restores.append((obj, plain))


def _restore(session) -> None:
    pairs = session.info.pop(_RESTORE, [])
    for obj, plain in pairs:
        for name, value in plain.items():
            set_committed_value(obj, name, value)


def _after_flush(session, flush_context) -> None:
    _restore(session)


def _after_rollback(session) -> None:
    _restore(session)


def _open_obj(target, only: set[str] | None = None) -> None:
    spec = SPECS.get(type(target).__name__)
    if spec is None:
        return
    version = getattr(target, "enc_version", None)
    state = inspect(target)
    if version is None or "enc_version" in state.unloaded:
        return
    if int(version or 0) != 1:
        return
    session = object_session(target)
    if session is None:
        raise TenantCryptoError("tenant_crypto_malformed")
    owner = _owner(target, session, spec)
    if owner is None:
        raise TenantCryptoError("tenant_key_missing")
    bidx_values = {}
    for source, bidx_name, _purpose in spec.bidx:
        token = getattr(target, bidx_name, None)
        if token:
            bidx_values[source] = token
    public_id = _public_id(target, spec, bidx_values)
    unloaded = set(inspect(target).unloaded)
    for name in spec.fields:
        if only is not None and name not in only:
            continue
        if name in unloaded:
            continue
        value = getattr(target, name)
        if value is None:
            continue
        opened = open_stored(
            session, user_id=int(owner), table=spec.table, column=name, public_id=public_id, value=value,
        )
        set_committed_value(target, name, opened)


def _on_load(target, context) -> None:
    _open_obj(target)


def _on_refresh(target, context, attrs) -> None:
    spec = SPECS.get(type(target).__name__)
    if spec is None:
        return
    if attrs is None:
        _open_obj(target)
        return
    reloaded = {name for name in spec.fields if name in attrs}
    if reloaded:
        _open_obj(target, only=reloaded)


def open_projected(session, *, user_id: int, table: str, column: str, public_id: str, enc_version, value):
    """Open a column selected without loading its entity. Version 0 is returned unchanged."""
    if value is None or not enc_version:
        return value
    if int(enc_version) != 1:
        return value
    return open_stored(
        session, user_id=int(user_id), table=table, column=column, public_id=str(public_id), value=value,
    )
