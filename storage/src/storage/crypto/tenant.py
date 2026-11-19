"""AES-256-GCM envelopes, blind indexes, and the tenant DEK cache.

Envelope: ``yenc:v1:<key_id>:<b64url nonce>:<b64url ciphertext||tag>``.
AAD: ``y-agent/v1:<internal user id>:<table>:<column>:<public row id>:1``.
Readers dispatch on ``enc_version``, never by sniffing a legacy value.
A version-1 value that is not a valid envelope fails closed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import time
import unicodedata
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

OPERATOR_EMAIL = "luohycs@gmail.com"
ENABLE_BLOCK_CODE = "encryption_enable_blocked"
LEGACY_ACCOUNT_CODE = "encryption_legacy_account"
_PREFIX = "yenc:v1:"
_AAD = "y-agent/v1"
_DEK_TTL_SECONDS = 600
_CACHE_MAX = 256


class TenantCryptoError(Exception):
    """Closed crypto failure. ``code`` is safe to return; the message is the code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class KeyMaterial:
    key_id: str
    dek: bytes
    bidx: bytes
    status: str


@dataclass(frozen=True)
class KeyState:
    """``none`` plaintext, ``active`` seal, ``disabled`` explicit downgrade, ``retired`` fail closed."""

    kind: str
    active: KeyMaterial | None = None


_lock = threading.Lock()
_dek_cache: dict[tuple, tuple[float, KeyMaterial]] = {}


def clear_cache() -> None:
    with _lock:
        _dek_cache.clear()


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def aad(user_id: int, table: str, column: str, public_id: str) -> bytes:
    return f"{_AAD}:{user_id}:{table}:{column}:{public_id}:1".encode("utf-8")


def encode_value(value) -> bytes:
    if isinstance(value, str):
        payload = {"t": "s", "v": value}
    else:
        payload = {"t": "j", "v": value}
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def decode_value(raw: bytes):
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TenantCryptoError("tenant_crypto_malformed") from exc
    kind = payload.get("t") if isinstance(payload, dict) else None
    if kind == "s" and isinstance(payload.get("v"), str):
        return payload["v"]
    if kind == "j" and "v" in payload:
        return payload["v"]
    raise TenantCryptoError("tenant_crypto_malformed")


def seal(dek: bytes, *, user_id: int, table: str, column: str, public_id: str, value, key_id: str) -> str:
    if not isinstance(key_id, str) or not key_id:
        raise TenantCryptoError("tenant_crypto_malformed")
    nonce = os.urandom(12)
    try:
        token = AESGCM(dek).encrypt(nonce, encode_value(value), aad(user_id, table, column, public_id))
    except Exception as exc:
        raise TenantCryptoError("tenant_crypto_malformed") from exc
    return f"{_PREFIX}{key_id}:{_b64e(nonce)}:{_b64e(token)}"


def open_envelope(dek: bytes, *, user_id: int, table: str, column: str, public_id: str, token: str):
    try:
        if not isinstance(token, str) or not token.startswith(_PREFIX):
            raise TenantCryptoError("tenant_crypto_malformed")
        rest = token[len(_PREFIX):]
        key_id, nonce_b64, ct_b64 = rest.split(":", 2)
        if not key_id:
            raise TenantCryptoError("tenant_crypto_malformed")
        nonce = _b64d(nonce_b64)
        ciphertext = _b64d(ct_b64)
        if len(nonce) != 12:
            raise TenantCryptoError("tenant_crypto_malformed")
        raw = AESGCM(dek).decrypt(nonce, ciphertext, aad(user_id, table, column, public_id))
    except TenantCryptoError:
        raise
    except Exception as exc:
        raise TenantCryptoError("tenant_crypto_malformed") from exc
    return decode_value(raw)


def envelope_key_id(token: str) -> str:
    try:
        if not isinstance(token, str) or not token.startswith(_PREFIX):
            raise TenantCryptoError("tenant_crypto_malformed")
        key_id = token[len(_PREFIX):].split(":", 1)[0]
        if not key_id:
            raise TenantCryptoError("tenant_crypto_malformed")
    except TenantCryptoError:
        raise
    except Exception as exc:
        raise TenantCryptoError("tenant_crypto_malformed") from exc
    return key_id


def blind_index(key: bytes, purpose: str, value: str) -> str:
    normalized = unicodedata.normalize("NFC", "" if value is None else str(value))
    digest = hmac.new(key, f"{purpose}\0{normalized}".encode("utf-8"), hashlib.sha256).digest()
    return _b64e(digest)


def master_keys() -> tuple[str, dict[str, bytes]]:
    """Read current configuration; closed errors never contain key material."""
    current = os.environ.get("Y_AGENT_TENANT_MASTER_KEY_ID", "").strip()
    raw = os.environ.get("Y_AGENT_TENANT_MASTER_KEYS", "")
    if not raw and not current:
        return "", {}
    try:
        values = json.loads(raw)
        if not isinstance(values, dict) or not values or not current:
            raise ValueError()
        keys = {}
        for key_id, value in values.items():
            if not isinstance(key_id, str) or not key_id or len(key_id) > 128:
                raise ValueError()
            if not isinstance(value, str):
                raise ValueError()
            key = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
            if len(key) != 32:
                raise ValueError()
            keys[key_id] = key
        if current not in keys:
            raise ValueError()
        return current, keys
    except Exception:
        raise TenantCryptoError("tenant_master_key_config_invalid") from None


def _master_key(master_key_id: str) -> bytes:
    _, keys = master_keys()
    if not keys:
        raise TenantCryptoError("tenant_master_key_unconfigured")
    if master_key_id not in keys:
        raise TenantCryptoError("tenant_master_key_unknown")
    return keys[master_key_id]


def _wrap_aad(user_id: int, purpose: str, key_id: str) -> bytes:
    return f"y-agent/kek/v1:{user_id}:{purpose}:{key_id}".encode("utf-8")


def wrap_key(user_id: int, purpose: str, key_id: str, plaintext: bytes,
             master_key_id: str) -> tuple[bytes, bytes]:
    key = _master_key(master_key_id)
    if len(plaintext) != 32:
        raise TenantCryptoError("tenant_key_malformed")
    nonce = os.urandom(12)
    return AESGCM(key).encrypt(nonce, plaintext, _wrap_aad(user_id, purpose, key_id)), nonce


def unwrap_key(user_id: int, purpose: str, key_id: str, wrapped: bytes,
               nonce: bytes, master_key_id: str) -> bytes:
    key = _master_key(master_key_id)
    try:
        if len(nonce) != 12 or len(wrapped) != 48:
            raise ValueError()
        plain = AESGCM(key).decrypt(nonce, wrapped, _wrap_aad(user_id, purpose, key_id))
        if len(plain) != 32:
            raise ValueError()
        return plain
    except Exception:
        raise TenantCryptoError("tenant_key_malformed") from None


def _cache_put(cache: dict, key, value, ttl: float) -> None:
    now = time.monotonic()
    with _lock:
        expired = [item for item, (stamp, _) in cache.items() if stamp <= now]
        for item in expired:
            cache.pop(item, None)
        while len(cache) >= _CACHE_MAX:
            cache.pop(next(iter(cache)))
        cache[key] = (time.monotonic() + ttl, value)


def _cache_get(cache: dict, key):
    now = time.monotonic()
    with _lock:
        found = cache.get(key)
        if found is None:
            return None
        if found[0] <= now:
            cache.pop(key, None)
            return None
        return found[1]


def _rows(session, user_id: int):
    from storage.entity.tenant_key import TenantKeyEntity

    return session.query(TenantKeyEntity).populate_existing().filter_by(user_id=user_id).all()


def _material(row) -> KeyMaterial:
    if row.status not in {"active", "retired", "disabled"}:
        raise TenantCryptoError("tenant_key_malformed")
    # A fresh row and currently configured KEK must agree before cache reuse.
    master = _master_key(row.master_key_id)
    cache_key = (row.user_id, row.key_id, row.status, row.master_key_id,
                 hashlib.sha256(master).digest(), bytes(row.wrapped_dek), bytes(row.wrap_nonce),
                 bytes(row.bidx_wrapped), bytes(row.bidx_nonce))
    cached = _cache_get(_dek_cache, cache_key)
    if cached is not None:
        return cached
    dek = unwrap_key(row.user_id, "dek", row.key_id, bytes(row.wrapped_dek),
                     bytes(row.wrap_nonce), row.master_key_id)
    bidx = unwrap_key(row.user_id, "bidx", row.key_id, bytes(row.bidx_wrapped),
                      bytes(row.bidx_nonce), row.master_key_id)
    material = KeyMaterial(key_id=row.key_id, dek=dek, bidx=bidx, status=row.status)
    _cache_put(_dek_cache, cache_key, material, _DEK_TTL_SECONDS)
    return material


def key_state(session, user_id: int) -> KeyState:
    if user_id is None:
        return KeyState("none")
    rows = _rows(session, int(user_id))
    active = next((row for row in rows if row.status == "active"), None)
    if active is not None:
        return KeyState("active", _material(active))
    if any(row.status == "disabled" for row in rows):
        return KeyState("disabled")
    return KeyState("retired" if rows else "none")


def material_for_key(session, user_id: int, key_id: str) -> KeyMaterial:
    from storage.entity.tenant_key import TenantKeyEntity

    row = (session.query(TenantKeyEntity).populate_existing()
           .filter_by(user_id=int(user_id), key_id=key_id).one_or_none())
    if row is None:
        raise TenantCryptoError("tenant_key_missing")
    return _material(row)


def encryption_active(session, user_id: int) -> bool:
    return key_state(session, user_id).kind == "active"


def blind_for_user(session, user_id: int, purpose: str, value: str) -> str | None:
    state = key_state(session, user_id)
    if state.kind != "active" or state.active is None:
        return None
    return blind_index(state.active.bidx, purpose, value)


def open_stored(session, *, user_id: int, table: str, column: str, public_id: str, value):
    if not isinstance(value, str):
        raise TenantCryptoError("tenant_crypto_malformed")
    material = material_for_key(session, user_id, envelope_key_id(value))
    return open_envelope(
        material.dek, user_id=user_id, table=table, column=column, public_id=public_id, token=value,
    )


def is_legacy_account(user) -> bool:
    email = (getattr(user, "email", None) or "").strip().lower()
    return email == OPERATOR_EMAIL


def enable_tenant(session, user_id: int) -> None:
    """Refuse every account. Existing accounts stay plaintext; 4371 still blocks new ones."""
    from storage.entity.user import UserEntity

    user = session.get(UserEntity, user_id)
    if user is None:
        raise TenantCryptoError("tenant_user_missing")
    if is_legacy_account(user):
        raise TenantCryptoError(LEGACY_ACCOUNT_CODE)
    if not getattr(user, "encryption_eligible", False):
        raise TenantCryptoError("encryption_not_eligible")
    raise TenantCryptoError(ENABLE_BLOCK_CODE)


def _insert_key(session, user_id: int, status: str) -> str:
    from storage.entity.tenant_key import TenantKeyEntity
    from storage.util import get_utc_iso8601_timestamp

    key_id = os.urandom(16).hex()
    dek = os.urandom(32)
    bidx = os.urandom(32)
    master_id, _ = master_keys()
    wrapped_dek, wrap_nonce = wrap_key(user_id, "dek", key_id, dek, master_id)
    bidx_wrapped, bidx_nonce = wrap_key(user_id, "bidx", key_id, bidx, master_id)
    row = TenantKeyEntity(
        user_id=user_id,
        key_id=key_id,
        status=status,
        wrapped_dek=wrapped_dek,
        wrap_nonce=wrap_nonce,
        bidx_wrapped=bidx_wrapped,
        bidx_nonce=bidx_nonce,
        kms_key_arn="",
        master_key_id=master_id,
        created_at=get_utc_iso8601_timestamp(),
    )
    session.add(row)
    clear_cache()
    return key_id


def rotate_dek(session, user_id: int) -> str:
    from storage.entity.tenant_key import TenantKeyEntity

    state = key_state(session, user_id)
    if state.kind != "active":
        raise TenantCryptoError("encryption_inactive")
    current = session.query(TenantKeyEntity).filter_by(user_id=user_id, status="active").one()
    current.status = "retired"
    session.flush()
    key_id = _insert_key(session, user_id, "active")
    clear_cache()
    return key_id


def rewrap_keys(session) -> int:
    """Rewrap both tenant keys with the current KEK; data envelopes stay intact."""
    from storage.entity.tenant_key import TenantKeyEntity

    master_id, _ = master_keys()
    _master_key(master_id)
    rows = session.query(TenantKeyEntity).populate_existing().with_for_update().all()
    try:
        for row in rows:
            for purpose, attr, nonce_attr in (("dek", "wrapped_dek", "wrap_nonce"),
                                               ("bidx", "bidx_wrapped", "bidx_nonce")):
                plain = unwrap_key(row.user_id, purpose, row.key_id, bytes(getattr(row, attr)),
                                   bytes(getattr(row, nonce_attr)), row.master_key_id)
                wrapped, nonce = wrap_key(row.user_id, purpose, row.key_id, plain, master_id)
                setattr(row, attr, wrapped)
                setattr(row, nonce_attr, nonce)
            row.master_key_id = master_id
            row.kms_key_arn = ""
    finally:
        clear_cache()
    return len(rows)


def shred_tenant(session, user_id: int) -> int:
    """Delete wrapped DEK rows and drop this process's DEK cache. Operator is refused.

    This does not erase ciphertext, a copied DEK, or a database snapshot. Those
    copies still decrypt until the copy and backup retention are gone.
    """
    from storage.entity.tenant_key import TenantKeyEntity
    from storage.entity.user import UserEntity

    user = session.get(UserEntity, user_id)
    if user is not None and is_legacy_account(user):
        raise TenantCryptoError("encryption_shred_refused")
    deleted = session.query(TenantKeyEntity).filter_by(user_id=user_id).delete()
    clear_cache()
    return int(deleted or 0)
