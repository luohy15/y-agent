"""Local acceptance for the tenant envelope. No database and no KMS."""

from __future__ import annotations

from storage.crypto.orm import _open_obj, apply_tenant_write, open_projected
from storage.crypto.query import match_bidx
from storage.crypto.tenant import (
    ENABLE_BLOCK_CODE,
    LEGACY_ACCOUNT_CODE,
    OPERATOR_EMAIL,
    KeyMaterial,
    KeyState,
    TenantCryptoError,
    blind_index,
    clear_cache,
    enable_tenant,
    is_legacy_account,
    material_for_key,
    open_envelope,
    seal,
    shred_tenant,
)
from storage.crypto import tenant as tenant_mod
from storage.crypto.orm import column_values
from storage.entity.bot_config import BotConfigEntity
from storage.entity.chat import ChatEntity
from storage.entity.user import UserEntity
from storage.repository.link import may_reuse_link, sealed_link_visible


def _check(name: str, ok: bool) -> None:
    if not ok:
        raise SystemExit(f"FAIL {name}")
    print(f"ok {name}")


class _User:
    def __init__(self, email: str, eligible: bool):
        self.email = email
        self.encryption_eligible = eligible


class _Query:
    def __init__(self, session):
        self.session = session

    def filter_by(self, **_kwargs):
        return self

    def delete(self):
        self.session.deleted += 1
        return 1

    def one_or_none(self):
        return None


class _Session:
    def __init__(self, user):
        self.user = user
        self.deleted = 0

    def get(self, _model, _user_id):
        return self.user

    def query(self, _model):
        return _Query(self)


def main() -> None:
    dek = b"\x11" * 32
    bidx = b"\x22" * 32
    token = seal(dek, user_id=7, table="todo", column="name", public_id="td_1", value="marker-2678", key_id="k1")
    opened = open_envelope(dek, user_id=7, table="todo", column="name", public_id="td_1", token=token)
    _check("roundtrip", opened == "marker-2678" and token.startswith("yenc:v1:k1:"))
    try:
        open_envelope(dek, user_id=8, table="todo", column="name", public_id="td_1", token=token)
    except TenantCryptoError as exc:
        _check("wrong tenant", exc.code == "tenant_crypto_malformed")
    else:
        raise SystemExit("FAIL wrong tenant")
    try:
        open_envelope(dek, user_id=7, table="todo", column="name", public_id="td_2", token=token)
    except TenantCryptoError:
        _check("moved row", True)
    else:
        raise SystemExit("FAIL moved row")
    try:
        open_envelope(dek, user_id=7, table="todo", column="desc", public_id="td_1", token=token)
    except TenantCryptoError:
        _check("moved column", True)
    else:
        raise SystemExit("FAIL moved column")
    try:
        open_envelope(b"\x33" * 32, user_id=7, table="todo", column="name", public_id="td_1", token=token)
    except TenantCryptoError:
        _check("wrong dek", True)
    else:
        raise SystemExit("FAIL wrong dek")
    try:
        open_envelope(dek, user_id=7, table="todo", column="name", public_id="td_1", token="marker-2678")
    except TenantCryptoError:
        _check("malformed", True)
    else:
        raise SystemExit("FAIL malformed")
    blob = {"n": 1, "ok": True}
    sealed = seal(dek, user_id=7, table="todo", column="history", public_id="td_1", value=blob, key_id="k1")
    _check("json", open_envelope(dek, user_id=7, table="todo", column="history", public_id="td_1", token=sealed) == blob)
    one = blind_index(bidx, "tag", "Work")
    _check("bidx stable", one == blind_index(bidx, "tag", "Work") and one != blind_index(bidx, "url", "Work"))
    legacy = _User(OPERATOR_EMAIL, True)
    try:
        enable_tenant(_Session(legacy), 1)
    except TenantCryptoError as exc:
        _check("operator never enabled", exc.code == LEGACY_ACCOUNT_CODE and is_legacy_account(legacy))
    else:
        raise SystemExit("FAIL operator")
    try:
        enable_tenant(_Session(_User("new@example.com", False)), 2)
    except TenantCryptoError as exc:
        _check("existing ineligible", exc.code == "encryption_not_eligible")
    else:
        raise SystemExit("FAIL ineligible")
    try:
        enable_tenant(_Session(_User("new@example.com", True)), 3)
    except TenantCryptoError as exc:
        _check("enable blocked", exc.code == ENABLE_BLOCK_CODE)
    else:
        raise SystemExit("FAIL blocked")
    try:
        shred_tenant(_Session(legacy), 1)
    except TenantCryptoError as exc:
        _check("operator shred refused", exc.code == "encryption_shred_refused")
    else:
        raise SystemExit("FAIL shred")
    hosted = _Session(_User("wu@example.com", False))
    clear_cache()
    retained = KeyMaterial(key_id="k1", dek=dek, bidx=bidx, status="active")
    tenant_mod._cache_put(tenant_mod._dek_cache, (9, "k1"), retained, 600)
    _check("cache hit before shred", material_for_key(hosted, 9, "k1").dek == dek)
    _check("shred deletes keys", shred_tenant(hosted, 9) == 1 and hosted.deleted == 1)
    try:
        material_for_key(hosted, 9, "k1")
    except TenantCryptoError as exc:
        _check("shred drops dek cache", exc.code == "tenant_key_missing")
    else:
        raise SystemExit("FAIL shred cache")
    backup = open_envelope(dek, user_id=7, table="todo", column="name", public_id="td_1", token=token)
    _check("backup dek still decrypts", backup == "marker-2678")
    _legacy_roundtrip()
    _link_activity_rewrite()
    print("acceptance ok")


def _legacy_roundtrip() -> None:
    marker = "marker-2678"
    row = ChatEntity(
        user_id=1, chat_id="c-legacy", title=marker,
        json_content='{"text":"marker-2678"}', search_text=marker, enc_version=0,
    )
    _check("legacy write", apply_tenant_write(row, KeyState("none"), 1) is None)
    _check(
        "legacy row unchanged",
        row.title == marker and row.json_content == '{"text":"marker-2678"}'
        and row.search_text == marker and (row.enc_version or 0) == 0
        and "yenc:" not in row.title and "yenc:" not in row.json_content,
    )
    read_back = open_projected(
        None, user_id=1, table="chat", column="title", public_id="c-legacy",
        enc_version=0, value=row.title,
    )
    _open_obj(row)
    _check("legacy read", read_back == marker and row.title == marker)
    tenant_mod._cache_put(tenant_mod._state_cache, 1, KeyState("none"), 60)
    clause = match_bidx(None, 1, ChatEntity.title, ChatEntity.title, "title", marker)
    _check("legacy filter stays plaintext", getattr(clause.right, "value", None) == marker)
    default = UserEntity.encryption_eligible.default.arg
    _check("eligible default false", default is False)
    _active_roundtrip()


def _active_roundtrip() -> None:
    from sqlalchemy.orm import Session
    from storage.entity.todo import TodoEntity

    marker = "marker-2678"
    dek = b"\x44" * 32
    material = KeyMaterial(key_id="k-active", dek=dek, bidx=b"\x55" * 32, status="active")
    clear_cache()
    tenant_mod._cache_put(tenant_mod._dek_cache, (4, "k-active"), material, 600)
    row = ChatEntity(
        user_id=4, chat_id="c-active", title=marker,
        json_content="{\"text\":\"marker-2678\"}", search_text=marker, enc_version=0,
    )
    restored = apply_tenant_write(row, KeyState("active", material), 4)
    opened = open_envelope(
        dek, user_id=4, table="chat", column="title", public_id="c-active", token=row.title,
    )
    _check("active write seals", restored is not None and opened == marker and row.enc_version == 1 and row.search_text is None)
    sealed_name = seal(
        dek, user_id=4, table="todo", column="name", public_id="td-open", value=marker, key_id="k-active",
    )
    session = Session()
    loaded = TodoEntity(
        user_id=4, todo_id="td-open", name=sealed_name, desc=None, progress=None,
        tags=None, history=["keep"], enc_version=1,
    )
    session.add(loaded)
    state = __import__("sqlalchemy").inspect(loaded)
    state.dict.pop("history", None)
    state.committed_state.pop("history", None)
    _open_obj(loaded)
    _check("open skips deferred history", loaded.name == marker and "history" in state.unloaded)
    partial = TodoEntity(user_id=4, todo_id="td-partial", name=marker)
    sealed_partial = apply_tenant_write(partial, KeyState("active", material), 4)
    partial_name = open_envelope(
        dek, user_id=4, table="todo", column="name", public_id="td-partial", token=partial.name,
    )
    _check(
        "pending partial row seals",
        sealed_partial is not None and partial_name == marker and partial.enc_version == 1,
    )
    bot = BotConfigEntity(user_id=4, name="bot-a", api_key=marker)
    sealed_bot = apply_tenant_write(bot, KeyState("active", material), 4)
    bot_key = open_envelope(
        dek, user_id=4, table="bot_config", column="api_key", public_id="bot-a", token=bot.api_key,
    )
    _check("pending bot seals unset fields", sealed_bot is not None and bot_key == marker and bot.enc_version == 1)

    class _Row:
        def __init__(self, value):
            self._value = value

        def __getitem__(self, index):
            if index != 0:
                raise IndexError(index)
            return self._value

        def __iter__(self):
            yield self._value

    cell = column_values(_Row("history-plain"), 1)[0]
    _check("single column is not a row", cell == "history-plain" and type(cell) is str)
    _check("refuse foreign link", may_reuse_link(9, 4) is False and sealed_link_visible(9, 4) is False)
    _check("reuse own or legacy link", may_reuse_link(4, 4) and may_reuse_link(None, 4) and sealed_link_visible(4, 4))
    clear_cache()


def _link_activity_rewrite() -> None:
    from sqlalchemy import update
    from sqlalchemy.orm import Session
    from storage.crypto.fields import SPECS
    from storage.crypto.orm import _before_flush, classified_set_write, install
    from storage.entity.link import LinkActivityEntity

    install()
    # Unbound sessions prove rejection occurs before any database access.
    with Session() as session:
        operations = (
            lambda: session.query(LinkActivityEntity).update({"url": "new-alias"}),
            lambda: session.execute(update(LinkActivityEntity).values(url="new-alias")),
            lambda: session.execute(update(LinkActivityEntity.__table__).values(url="new-alias")),
            lambda: session.execute(update(LinkActivityEntity), [{"id": 1, "url": "new-alias"}]),
            lambda: session.execute(update(LinkActivityEntity).ordered_values((LinkActivityEntity.url, "new-alias"))),
        )
        for operation in operations:
            try:
                operation()
            except TenantCryptoError as exc:
                if exc.code != "tenant_crypto_set_write":
                    raise
            else:
                raise SystemExit("FAIL set write refused")
    from storage.crypto.orm import _model
    for name, spec in SPECS.items():
        model = _model(name)
        for column in spec.fields + spec.clear + tuple(item[1] for item in spec.bidx) + ("enc_version",):
            if not classified_set_write(update(model).values({column: None})):
                raise SystemExit(f"FAIL set write refused: {spec.table}.{column}")
    _check("set write refused", not classified_set_write(update(LinkActivityEntity).values(download_status="done")))

    clear_cache()
    material = KeyMaterial(key_id="k-rewrite", dek=b"\x66" * 32, bidx=b"\x77" * 32, status="active")
    tenant_mod._cache_put(tenant_mod._dek_cache, (4, material.key_id), material, 600)
    alias = "https://example.com/new-alias"
    with Session() as session:
        row = LinkActivityEntity(user_id=4, activity_id="a-rewrite", link_id=1, source="rss", title=None,
                                 enc_version=1, url=seal(material.dek, user_id=4, table="link_activity",
                                 column="url", public_id="a-rewrite", value="old-alias", key_id=material.key_id))
        session.add(row)
        _open_obj(row)
        row.url = alias
        tenant_mod._cache_put(tenant_mod._state_cache, 4, KeyState("active", material), 60)
        _before_flush(session, None, None)
        _check("activity rewrite reseals", row.enc_version == 1 and row.url.startswith("yenc:")
               and row.url_bidx == blind_index(material.bidx, "url", alias)
               and open_envelope(material.dek, user_id=4, table="link_activity", column="url",
                                 public_id="a-rewrite", token=row.url) == alias)
        _open_obj(row)
        row.url = alias + "-disabled"
        tenant_mod._cache_put(tenant_mod._state_cache, 4, KeyState("disabled"), 60)
        _before_flush(session, None, None)
        _check("disabled rewrite is plaintext", row.enc_version == 0 and row.url == alias + "-disabled"
               and row.url_bidx is None)
        row.enc_version = 1
        try:
            _open_obj(row)
        except TenantCryptoError as exc:
            _check("plaintext v1 url closed", exc.code == "tenant_crypto_malformed")
        else:
            raise SystemExit("FAIL plaintext v1 url closed")
        tenant_mod._cache_put(tenant_mod._state_cache, 4, KeyState("retired"), 60)
        try:
            _before_flush(session, None, None)
        except TenantCryptoError as exc:
            _check("retired rewrite closed", exc.code == "tenant_key_retired")
        else:
            raise SystemExit("FAIL retired rewrite closed")
    clear_cache()


if __name__ == "__main__":
    main()
