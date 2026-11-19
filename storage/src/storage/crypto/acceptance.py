"""Local acceptance for the tenant envelope. No database, network, or real master keys."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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


_KEY_ROWS = {}


def _fixture(user_id, material):
    master_id, _ = tenant_mod.master_keys()
    dek, nonce = tenant_mod.wrap_key(user_id, "dek", material.key_id, material.dek, master_id)
    bidx, bnonce = tenant_mod.wrap_key(user_id, "bidx", material.key_id, material.bidx, master_id)
    row = SimpleNamespace(user_id=user_id, key_id=material.key_id, status=material.status,
                          master_key_id=master_id, wrapped_dek=dek, wrap_nonce=nonce,
                          bidx_wrapped=bidx, bidx_nonce=bnonce, kms_key_arn="")
    _KEY_ROWS[(user_id, material.key_id)] = row
    return row


class _Query:
    def __init__(self, session):
        self.session = session
        self.filters = {}

    def filter_by(self, **kwargs):
        self.filters.update(kwargs)
        return self

    def populate_existing(self):
        return self

    def with_for_update(self):
        return self

    def all(self):
        return [row for row in _KEY_ROWS.values()
                if all(getattr(row, key) == value for key, value in self.filters.items())]

    def delete(self):
        self.session.deleted += 1
        for row in self.all():
            _KEY_ROWS.pop((row.user_id, row.key_id))
        return 1

    def one_or_none(self):
        rows = self.all()
        return rows[0] if rows else None


class _Session:
    def __init__(self, user):
        self.user = user
        self.deleted = 0

    def get(self, _model, _user_id):
        return self.user

    def query(self, _model):
        return _Query(self)


def _main() -> None:
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
    _fixture(9, retained)
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
    _KEY_ROWS.clear()
    clause = match_bidx(_Session(None), 1, ChatEntity.title, ChatEntity.title, "title", marker)
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
    _fixture(4, material)
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
    _KEY_ROWS.clear()
    material = KeyMaterial(key_id="k-rewrite", dek=b"\x66" * 32, bidx=b"\x77" * 32, status="active")
    _fixture(4, material)
    alias = "https://example.com/new-alias"
    with Session() as session:
        row = LinkActivityEntity(user_id=4, activity_id="a-rewrite", link_id=1, source="rss", title=None,
                                 enc_version=1, url=seal(material.dek, user_id=4, table="link_activity",
                                 column="url", public_id="a-rewrite", value="old-alias", key_id=material.key_id))
        session.add(row)
        _open_obj(row)
        row.url = alias
        _KEY_ROWS[(4, material.key_id)].status = "active"
        _before_flush(session, None, None)
        _check("activity rewrite reseals", row.enc_version == 1 and row.url.startswith("yenc:")
               and row.url_bidx == blind_index(material.bidx, "url", alias)
               and open_envelope(material.dek, user_id=4, table="link_activity", column="url",
                                 public_id="a-rewrite", token=row.url) == alias)
        _open_obj(row)
        row.url = alias + "-disabled"
        for key_row in _KEY_ROWS.values():
            key_row.status = "disabled"
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
        for key_row in _KEY_ROWS.values():
            key_row.status = "retired"
        try:
            _before_flush(session, None, None)
        except TenantCryptoError as exc:
            _check("retired rewrite closed", exc.code == "tenant_key_retired")
        else:
            raise SystemExit("FAIL retired rewrite closed")
    clear_cache()


def _closed(name, operation, code=None):
    try:
        operation()
    except TenantCryptoError as exc:
        _check(name, code is None or exc.code == code)
    else:
        raise SystemExit(f"FAIL {name}")


def _master_acceptance():
    from storage.crypto.guard import validate_master_key_ids
    _KEY_ROWS.clear()
    material = KeyMaterial("fixture", b"d" * 32, b"b" * 32, "active")
    row = _fixture(59, material)
    session = _Session(None)
    _check("KEK roundtrip", material_for_key(session, 59, "fixture") == material)
    for name, uid, purpose, kid in (("KEK wrong tenant", 60, "dek", "fixture"),
                                     ("KEK wrong purpose", 59, "bidx", "fixture"),
                                     ("KEK moved row", 59, "dek", "other")):
        _closed(name, lambda uid=uid, purpose=purpose, kid=kid: tenant_mod.unwrap_key(uid, purpose, kid, row.wrapped_dek, row.wrap_nonce, "old"))
    _closed("KEK malformed nonce", lambda: tenant_mod.unwrap_key(59, "dek", "fixture", row.wrapped_dek, b"", "old"))
    _closed("unknown KEK", lambda: tenant_mod.unwrap_key(59, "dek", "fixture", row.wrapped_dek, row.wrap_nonce, "absent"))
    _closed("guard unknown id", lambda: validate_master_key_ids(["absent"]))
    # Simulates a different process deleting the row: deliberately do not clear.
    _KEY_ROWS.clear()
    _closed("remote shred defeats warm cache", lambda: material_for_key(session, 59, "fixture"), "tenant_key_missing")
    _KEY_ROWS[(59, "fixture")] = row
    os.environ["Y_AGENT_TENANT_MASTER_KEY_ID"] = "new"
    _check("KEK rewrap count", tenant_mod.rewrap_keys(session) == 1)
    _check("KEK rewrap preserves bytes", row.master_key_id == "new" and material_for_key(session, 59, "fixture") == material)
    with patch.dict(os.environ, {"Y_AGENT_TENANT_MASTER_KEYS": json.dumps({"old": tenant_mod._b64e(b"o" * 32)}),
                                 "Y_AGENT_TENANT_MASTER_KEY_ID": "old"}):
        _closed("removed KEK defeats warm cache", lambda: material_for_key(session, 59, "fixture"))
    with patch.dict(os.environ, {"Y_AGENT_TENANT_MASTER_KEYS": "", "Y_AGENT_TENANT_MASTER_KEY_ID": ""}), \
            patch("storage.crypto.custody.private_key_path", return_value=Path("/no/such/tenant-master-key-2678")), \
            patch("storage.crypto.custody.read_ssm", return_value=None):
        _closed("no KEK closes reads", lambda: material_for_key(session, 59, "fixture"))
    row.wrapped_dek = b"x" * 48
    _closed("modified wrap defeats warm cache", lambda: material_for_key(session, 59, "fixture"))
    _fixture(59, material)
    _voice_acceptance(session)


def _voice_acceptance(session):
    from contextlib import contextmanager
    from storage.service import voice_store as voice

    @contextmanager
    def db():
        yield session

    with patch("storage.database.base.get_db", db):
        raw = b"\x00\x01" * 50
        stored, meta = voice._seal_voice(59, "take", raw, column="part:000000")
        _check("voice part sealed", stored.startswith(b"yenc:v1:") and meta["yenc"] == "1"
               and int(meta["stored_byte_count"]) == len(stored))
        _check("voice part roundtrip", voice._open_voice(59, "take", stored, sealed=True, column="part:000000") == raw)
        _closed("voice part moved", lambda: voice._open_voice(59, "take", stored, sealed=True, column="part:000001"))
        _voice_parts_flow()
        _KEY_ROWS.clear()
        _closed("voice sealed after shred", lambda: voice._open_voice(59, "take", stored, sealed=True, column="part:000000"))


def _voice_parts_flow():
    from io import BytesIO
    from storage.service import voice_store as voice
    from botocore.exceptions import ClientError

    class Objects:
        def __init__(self):
            self.rows = {}

        def head_object(self, *, Bucket, Key):
            if Key not in self.rows:
                raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
            row = self.rows[Key]
            return {"Metadata": row["Metadata"], "ContentLength": len(row["Body"]), "VersionId": "v1"}

        def put_object(self, **values):
            self.rows[values["Key"]] = values
            return {"VersionId": "v1"}

        def get_object(self, *, Bucket, Key, VersionId):
            return {**self.head_object(Bucket=Bucket, Key=Key), "Body": BytesIO(self.rows[Key]["Body"])}

        def list_objects_v2(self, *, Bucket, Prefix):
            return {"Contents": [{"Key": key} for key in self.rows if key.startswith(Prefix)]}

    objects = Objects()
    take = "00000000-0000-4000-8000-000000000001"
    data = b"\x00\x01" * 100
    with patch.object(voice, "_require_owner", return_value="fixture"), \
            patch.object(voice, "_store", return_value=(objects, "fixture")), \
            patch.object(voice, "_cleanup_parts"):
        result = voice.put_part(59, take, 0, 0, data=data, audio_format="pcm", client=objects)
        replay = voice.put_part(59, take, 0, 0, data=data, audio_format="pcm", client=objects)
        _check("voice retry idempotent", not result["duplicate"] and replay["duplicate"])
        part = next(iter(objects.rows.values()))
        _check("voice stored part sealed", part["Body"].startswith(b"yenc:v1:") and part["Metadata"]["yenc"] == "1")
        final = voice.finalize_parts(59, take, part_count=1, audio_format="pcm", duration_ms=100, client=objects)
        opened = voice.get_object(59, take, version_id=final["version_id"], client=objects)
        _check("voice finalize decrypts parts", opened == voice._assemble_wav(data, "pcm")
               and final["byte_count"] == len(data) + 44)
        replay = voice.finalize_parts(59, take, part_count=1, audio_format="pcm", duration_ms=100, client=objects)
        _check("voice finalize replay", replay == final)


def _write_key_file(path: Path, payload: dict, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.chmod(path, mode)


def _custody_acceptance() -> None:
    from botocore.exceptions import ClientError
    from storage.crypto import custody

    clear_cache()
    marker = "SECRETMARKER"
    key = tenant_mod._b64e(b"k" * 32)
    other = tenant_mod._b64e(b"m" * 32)
    good = {"current": "file", "keys": {"file": key}}
    calls = {"ssm": 0}

    def forbidden_ssm():
        calls["ssm"] += 1
        raise AssertionError("lower priority source was used")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / "tenant-master-key"
        _write_key_file(path, good)
        with patch.dict(os.environ, {"Y_AGENT_TENANT_MASTER_KEYS": json.dumps({"env": other}),
                                     "Y_AGENT_TENANT_MASTER_KEY_ID": "env"}), \
                patch.object(custody, "private_key_path", return_value=path), \
                patch.object(custody, "read_ssm", forbidden_ssm):
            current, keys = tenant_mod.master_keys()
            _check("env beats file and ssm", current == "env" and calls["ssm"] == 0 and "file" not in keys)
        with patch.dict(os.environ, {"Y_AGENT_TENANT_MASTER_KEYS": marker, "Y_AGENT_TENANT_MASTER_KEY_ID": "env"}), \
                patch.object(custody, "read_ssm", forbidden_ssm):
            try:
                tenant_mod.master_keys()
            except TenantCryptoError as exc:
                _check("invalid env does not fall through", exc.code == "tenant_master_key_config_invalid"
                       and marker not in str(exc) and calls["ssm"] == 0)
            else:
                raise SystemExit("FAIL invalid env")
        calls["ssm"] = 0
        _write_key_file(path, {"current": "file", "keys": {"file": "not-base64"}}, 0o644)
        with patch.dict(os.environ, {"Y_AGENT_TENANT_MASTER_KEYS": "", "Y_AGENT_TENANT_MASTER_KEY_ID": ""}), \
                patch.object(custody, "private_key_path", return_value=path), \
                patch.object(custody, "read_ssm", forbidden_ssm):
            try:
                custody.load_private_file(path)
            except TenantCryptoError as exc:
                _check("mode 0644 rejected", exc.code == "tenant_master_key_config_invalid" and calls["ssm"] == 0)
            else:
                raise SystemExit("FAIL mode")
        link = root / "link"
        link.symlink_to(path)
        try:
            custody.load_private_file(link)
        except TenantCryptoError:
            _check("symlink rejected", True)
        else:
            raise SystemExit("FAIL symlink")
        _write_key_file(path, {"current": "missing", "keys": {"file": key}})
        try:
            custody.load_private_file(path)
        except TenantCryptoError:
            _check("missing current rejected", True)
        else:
            raise SystemExit("FAIL current")
        _write_key_file(path, {"not": "json"})
        path.write_text("{", encoding="utf-8")
        os.chmod(path, 0o600)
        try:
            custody.load_private_file(path)
        except TenantCryptoError:
            _check("malformed file rejected", True)
        else:
            raise SystemExit("FAIL malformed")
        inside = Path(".cache/a5-tenant-master-key")
        inside.parent.mkdir(parents=True, exist_ok=True)
        try:
            _write_key_file(inside, good)
            try:
                custody.load_private_file(inside)
            except TenantCryptoError:
                _check("checkout file rejected", True)
            else:
                raise SystemExit("FAIL checkout")
        finally:
            inside.unlink(missing_ok=True)
        _write_key_file(path, good)
        loaded = custody.load_private_file(path)
        _check("mode 0600 accepted", loaded is not None and loaded[0] == "file" and marker not in repr(loaded[0]))
        clear_cache()

        def ssm_once(*_args, **_kwargs):
            calls["ssm"] += 1
            return ("ssm", { "ssm": b"s" * 32 })

        clock = {"t": 1000.0}
        with patch.dict(os.environ, {"Y_AGENT_TENANT_MASTER_KEYS": "", "Y_AGENT_TENANT_MASTER_KEY_ID": "",
                                     custody.PARAMETER_ENV: custody.PRODUCTION_PARAMETER}), \
                patch.object(custody, "private_key_path", return_value=root / "absent-key"), \
                patch.object(custody, "read_ssm", ssm_once), \
                patch.object(tenant_mod, "_now", lambda: clock["t"]):
            first = tenant_mod.master_keys()
            second = tenant_mod.master_keys()
            _check("ssm cache 300s", first[0] == "ssm" and second[0] == "ssm" and calls["ssm"] == 1)
            clock["t"] = 1400.0
            third = tenant_mod.master_keys()
            _check("ssm cache expires", third[0] == "ssm" and calls["ssm"] == 2)
        clear_cache()
        calls["ssm"] = 0
        with patch.dict(os.environ, {"Y_AGENT_TENANT_MASTER_KEYS": "", "Y_AGENT_TENANT_MASTER_KEY_ID": ""}), \
                patch.object(custody, "private_key_path", return_value=path), \
                patch.object(custody, "read_ssm", forbidden_ssm):
            _check("file beats ssm", tenant_mod.master_keys()[0] == "file" and calls["ssm"] == 0)
        path.write_text("{", encoding="utf-8")
        os.chmod(path, 0o600)
        with patch.dict(os.environ, {"Y_AGENT_TENANT_MASTER_KEYS": "", "Y_AGENT_TENANT_MASTER_KEY_ID": ""}), \
                patch.object(custody, "private_key_path", return_value=path), \
                patch.object(custody, "read_ssm", forbidden_ssm):
            try:
                tenant_mod.master_keys()
            except TenantCryptoError as exc:
                _check("invalid file does not fall through", exc.code == "tenant_master_key_config_invalid"
                       and calls["ssm"] == 0)
            else:
                raise SystemExit("FAIL invalid file")
        absent = root / "no-key"
        client = type("Client", (), {})()
        client.get_parameter = lambda **kwargs: (_ for _ in ()).throw(ClientError(
            {"Error": {"Code": "ParameterNotFound"}}, "GetParameter"))
        _check("ssm absent is dormant", custody.read_ssm(client) is None)
        denied = type("Client", (), {})()
        denied.get_parameter = lambda **kwargs: (_ for _ in ()).throw(ClientError(
            {"Error": {"Code": "AccessDeniedException"}}, "GetParameter"))
        try:
            custody.read_ssm(denied)
        except TenantCryptoError as exc:
            _check("ssm denial closed", exc.code == "tenant_master_key_unavailable")
        else:
            raise SystemExit("FAIL ssm denial")
        bad = type("Client", (), {})()
        bad.get_parameter = lambda **kwargs: {"Parameter": {"Type": "SecureString", "Value": marker}}
        try:
            custody.read_ssm(bad)
        except TenantCryptoError as exc:
            _check("invalid ssm closed", exc.code == "tenant_master_key_config_invalid" and marker not in str(exc))
        else:
            raise SystemExit("FAIL invalid ssm")
        plain = type("Client", (), {})()
        plain.get_parameter = lambda **kwargs: {"Parameter": {"Type": "String", "Value": json.dumps(good)}}
        try:
            custody.read_ssm(plain)
        except TenantCryptoError as exc:
            _check("string parameter rejected", exc.code == "tenant_master_key_config_invalid")
        else:
            raise SystemExit("FAIL string parameter")
        file_cfg = ("file", {"file": b"k" * 32})
        ssm_cfg = ("file", {"file": b"s" * 32})
        try:
            custody.source_parity(None, file_cfg, ssm_cfg)
        except TenantCryptoError as exc:
            _check("parity mismatch", exc.code == "tenant_key_parity_mismatch")
        else:
            raise SystemExit("FAIL parity")
        custody.source_parity(None, None, None)
        _check("parity dormant", True)
        with patch.dict(os.environ, {"Y_AGENT_TENANT_MASTER_KEYS": "", "Y_AGENT_TENANT_MASTER_KEY_ID": "",
                                     custody.PARAMETER_ENV: ""}), \
                patch.object(custody, "private_key_path", return_value=absent), \
                patch.object(custody, "read_ssm", forbidden_ssm):
            _check("untargeted runtime stays dormant", tenant_mod.master_keys() == ("", {}) and calls["ssm"] == 0)
        with patch.dict(os.environ, {"Y_AGENT_TENANT_MASTER_KEYS": "", "Y_AGENT_TENANT_MASTER_KEY_ID": "",
                                     custody.PARAMETER_ENV: "not-a-parameter"}), \
                patch.object(custody, "private_key_path", return_value=absent), \
                patch.object(custody, "read_ssm", forbidden_ssm):
            try:
                tenant_mod.master_keys()
            except TenantCryptoError as exc:
                _check("bad parameter target closed", exc.code == "tenant_master_key_config_invalid"
                       and calls["ssm"] == 0)
            else:
                raise SystemExit("FAIL bad parameter")
        def _boom_client(*_args, **_kwargs):
            raise RuntimeError("SECRET-ENDPOINT")
        with patch.dict(os.environ, {custody.PARAMETER_ENV: custody.PRODUCTION_PARAMETER}), \
                patch("boto3.client", _boom_client):
            try:
                custody.read_ssm()
            except TenantCryptoError as exc:
                _check("ssm client error closed", exc.code == "tenant_master_key_unavailable"
                       and "SECRET-ENDPOINT" not in str(exc))
            else:
                raise SystemExit("FAIL client error")
        class _CopyClient:
            def __init__(self, value=None):
                self.value = value
                self.puts = []
            def get_parameter(self, **_kwargs):
                if self.value is None:
                    raise ClientError({"Error": {"Code": "ParameterNotFound"}}, "GetParameter")
                return {"Parameter": {"Type": "SecureString", "Value": self.value}}
            def put_parameter(self, **kwargs):
                self.puts.append(kwargs["Name"])
                self.value = kwargs["Value"]
        fresh = ("prod", {"prod": b"k" * 32})
        empty_client = _CopyClient()
        try:
            custody.copy_to_ssm(empty_client, fresh, target="production", stack="y-agent-test",
                                parameter=custody.PRODUCTION_PARAMETER)
        except TenantCryptoError as exc:
            _check("nonproduction copy refused", exc.code == "tenant_master_key_config_invalid"
                   and empty_client.puts == [])
        else:
            raise SystemExit("FAIL nonproduction copy")
        other = _CopyClient()
        try:
            custody.copy_to_ssm(other, fresh, target="test", stack="", parameter=custody.PRODUCTION_PARAMETER)
        except TenantCryptoError:
            _check("nontarget copy refused", other.puts == [])
        else:
            raise SystemExit("FAIL nontarget")
        held = json.dumps({"current": "old", "keys": {"old": tenant_mod._b64e(b"o" * 32)}})
        drop = _CopyClient(held)
        try:
            custody.copy_to_ssm(drop, fresh, target="production", stack="", parameter=custody.PRODUCTION_PARAMETER)
        except TenantCryptoError:
            _check("dropped key id refused", drop.puts == [])
        else:
            raise SystemExit("FAIL dropped key")
        changed = json.dumps({"current": "prod", "keys": {"prod": tenant_mod._b64e(b"z" * 32)}})
        clash = _CopyClient(changed)
        try:
            custody.copy_to_ssm(clash, fresh, target="production", stack="", parameter=custody.PRODUCTION_PARAMETER)
        except TenantCryptoError:
            _check("replaced key bytes refused", clash.puts == [])
        else:
            raise SystemExit("FAIL replaced bytes")
        kept = _CopyClient()
        custody.copy_to_ssm(kept, fresh, target="production", stack="", parameter=custody.PRODUCTION_PARAMETER)
        _check("production copy writes one path", kept.puts == [custody.PRODUCTION_PARAMETER])
        with patch.dict(os.environ, {"Y_AGENT_TENANT_MASTER_KEYS": "", "Y_AGENT_TENANT_MASTER_KEY_ID": "",
                                     custody.PARAMETER_ENV: custody.PRODUCTION_PARAMETER}), \
                patch.object(custody, "private_key_path", return_value=absent), \
                patch.object(custody, "read_ssm", return_value=None):
            _check("no source stays dormant", tenant_mod.master_keys() == ("", {}))
    _readiness_acceptance()
    clear_cache()


def _readiness_acceptance() -> None:
    from fastapi import HTTPException
    from api.controller import tenant_encryption as controller

    class _User:
        email = "wu@example.com"
        encryption_eligible = False

    class _Session:
        def get(self, _model, _user_id):
            return _User()

        def query(self, _model):
            return self

        def filter_by(self, **_kwargs):
            return self

        def all(self):
            return []

    class _Request:
        class state:
            user_id = 7

    from contextlib import contextmanager

    @contextmanager
    def _db():
        yield _Session()

    with patch.object(controller, "get_module_maintainer_user_id", return_value=7), \
            patch.object(controller, "get_db", _db), \
            patch.object(tenant_mod, "master_keys", return_value=("kid", {"kid": b"k" * 32})):
        body = controller.status(_Request(), 59)
    encoded = json.dumps(body)
    _check("readiness configured", body["master_key_configured"] is True and body["master_key_id"] == "kid"
           and "k" * 16 not in encoded and "keys" in body)
    with patch.object(controller, "get_module_maintainer_user_id", return_value=7), \
            patch.object(controller, "get_db", _db), \
            patch.object(tenant_mod, "master_keys", return_value=("", {})):
        empty = controller.status(_Request(), 59)
    _check("readiness dormant", empty["master_key_configured"] is False and empty["master_key_id"] is None)
    def _bad():
        raise TenantCryptoError("tenant_master_key_config_invalid")
    with patch.object(controller, "get_module_maintainer_user_id", return_value=7), \
            patch.object(controller, "get_db", _db), \
            patch("storage.crypto.tenant.master_keys", _bad):
        try:
            controller.status(_Request(), 59)
        except HTTPException as exc:
            _check("invalid readiness closed", exc.status_code == 409 and exc.detail == "tenant_master_key_config_invalid")
        else:
            raise SystemExit("FAIL readiness fallthrough")


def main():
    from sqlalchemy.orm import Session
    from storage.entity.tenant_key import TenantKeyEntity
    original = Session.query

    def query(session, *entities, **kwargs):
        if entities == (TenantKeyEntity,):
            return _Query(session)
        return original(session, *entities, **kwargs)

    # Published fixed fixtures only; never a usable generated production key.
    config = {"old": tenant_mod._b64e(b"o" * 32), "new": tenant_mod._b64e(b"n" * 32)}
    with patch.dict(os.environ, {"Y_AGENT_TENANT_MASTER_KEYS": json.dumps(config),
                                 "Y_AGENT_TENANT_MASTER_KEY_ID": "old"}), patch.object(Session, "query", query):
        _main()
        _master_acceptance()
    clear_cache()
    _KEY_ROWS.clear()
    _custody_acceptance()
    print("master-key acceptance ok")


if __name__ == "__main__":
    main()
