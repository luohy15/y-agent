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
_NEGATIVE_TTL_SECONDS = 60
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
_state_cache: dict[int, tuple[float, KeyState]] = {}
_dek_cache: dict[tuple[int, str], tuple[float, KeyMaterial]] = {}


def clear_cache() -> None:
    with _lock:
        _state_cache.clear()
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


def kms_arn() -> str:
    return os.environ.get("Y_AGENT_TENANT_KMS_KEY_ARN", "").strip()


def _kms():
    import boto3

    return boto3.client("kms", region_name="us-east-1")


def _context(user_id: int, purpose: str, key_id: str) -> dict:
    return {"tenant": str(user_id), "purpose": purpose, "key_id": key_id}


def wrap_key(user_id: int, purpose: str, key_id: str, plaintext: bytes) -> bytes:
    arn = kms_arn()
    if not arn:
        raise TenantCryptoError("kms_unconfigured")
    response = _kms().encrypt(KeyId=arn, Plaintext=plaintext, EncryptionContext=_context(user_id, purpose, key_id))
    blob = response.get("CiphertextBlob")
    if not isinstance(blob, (bytes, bytearray)) or not blob:
        raise TenantCryptoError("kms_unconfigured")
    return bytes(blob)


def unwrap_key(user_id: int, purpose: str, key_id: str, wrapped: bytes) -> bytes:
    arn = kms_arn()
    if not arn:
        raise TenantCryptoError("kms_unconfigured")
    response = _kms().decrypt(
        CiphertextBlob=wrapped, EncryptionContext=_context(user_id, purpose, key_id), KeyId=arn,
    )
    plain = response.get("Plaintext")
    if not isinstance(plain, (bytes, bytearray)) or len(plain) != 32:
        raise TenantCryptoError("tenant_key_missing")
    return bytes(plain)


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

    return session.query(TenantKeyEntity).filter_by(user_id=user_id).all()


def _material(row) -> KeyMaterial:
    cached = _cache_get(_dek_cache, (row.user_id, row.key_id))
    if cached is not None:
        return cached
    dek = unwrap_key(row.user_id, "dek", row.key_id, bytes(row.wrapped_dek))
    bidx = unwrap_key(row.user_id, "bidx", row.key_id, bytes(row.bidx_wrapped))
    material = KeyMaterial(key_id=row.key_id, dek=dek, bidx=bidx, status=row.status)
    _cache_put(_dek_cache, (row.user_id, row.key_id), material, _DEK_TTL_SECONDS)
    return material


def key_state(session, user_id: int) -> KeyState:
    if user_id is None:
        return KeyState("none")
    cached = _cache_get(_state_cache, int(user_id))
    if cached is not None:
        return cached
    rows = _rows(session, int(user_id))
    active = next((row for row in rows if row.status == "active"), None)
    if active is not None:
        state = KeyState("active", _material(active))
        _cache_put(_state_cache, int(user_id), state, _DEK_TTL_SECONDS)
        return state
    if any(row.status == "disabled" for row in rows):
        state = KeyState("disabled")
    elif rows:
        state = KeyState("retired")
    else:
        state = KeyState("none")
    _cache_put(_state_cache, int(user_id), state, _NEGATIVE_TTL_SECONDS)
    return state


def material_for_key(session, user_id: int, key_id: str) -> KeyMaterial:
    cached = _cache_get(_dek_cache, (int(user_id), key_id))
    if cached is not None:
        return cached
    from storage.entity.tenant_key import TenantKeyEntity

    row = session.query(TenantKeyEntity).filter_by(user_id=int(user_id), key_id=key_id).one_or_none()
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
    row = TenantKeyEntity(
        user_id=user_id,
        key_id=key_id,
        status=status,
        wrapped_dek=wrap_key(user_id, "dek", key_id, dek),
        wrap_nonce=b"",
        bidx_wrapped=wrap_key(user_id, "bidx", key_id, bidx),
        bidx_nonce=b"",
        kms_key_arn=kms_arn(),
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
    """Re-wrap DEKs with the current CMK. Data envelopes are not rewritten."""
    from storage.entity.tenant_key import TenantKeyEntity

    arn = kms_arn()
    if not arn:
        raise TenantCryptoError("kms_unconfigured")
    rows = session.query(TenantKeyEntity).all()
    client = _kms()
    for row in rows:
        for purpose, attr in (("dek", "wrapped_dek"), ("bidx", "bidx_wrapped")):
            blob = bytes(getattr(row, attr))
            response = client.re_encrypt(
                CiphertextBlob=blob,
                SourceEncryptionContext=_context(row.user_id, purpose, row.key_id),
                DestinationKeyId=arn,
                DestinationEncryptionContext=_context(row.user_id, purpose, row.key_id),
            )
            setattr(row, attr, response["CiphertextBlob"])
        row.kms_key_arn = arn
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
