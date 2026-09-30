"""Envelope encryption for MCP credential material (todo 3796).

Each record gets a fresh AES-256 data key from KMS (`GenerateDataKey`), is
sealed with AES-GCM, and stores only the ciphertext, nonce, KMS-encrypted data
key and key id. The authenticated context (deployment, owner public id,
connector id, identity generation, payload kind) is both the KMS encryption
context and the GCM associated data, so ciphertext moved to another owner,
connector, identity or kind does not decrypt.

The master key lives only in KMS (`Y_AGENT_MCP_KMS_KEY_ID`); an unset key or an
unreachable KMS raises `McpKeyUnavailable` and never falls back to plaintext.
Tests inject a fake provider through `set_key_provider`.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Optional, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class McpKeyUnavailable(Exception):
    """No usable key material: deny access, never degrade to plaintext."""


class McpCiphertextInvalid(Exception):
    """Ciphertext does not authenticate under the supplied context."""


@dataclass(frozen=True)
class Envelope:
    key_id: str
    encrypted_data_key: str
    nonce: str
    ciphertext: str


class KeyProvider(Protocol):
    def generate_data_key(self, context: dict[str, str]) -> tuple[str, bytes, bytes]:
        """Return (key_id, plaintext 32-byte key, encrypted key)."""

    def decrypt_data_key(self, key_id: str, encrypted_key: bytes, context: dict[str, str]) -> bytes:
        ...


class KmsKeyProvider:
    def __init__(self, key_id: str, client=None):
        self.key_id = key_id
        self._client = client

    def _kms(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("kms")
        return self._client

    def generate_data_key(self, context):
        try:
            out = self._kms().generate_data_key(KeyId=self.key_id, KeySpec="AES_256",
                                                EncryptionContext=context)
        except Exception as err:
            raise McpKeyUnavailable("key service unavailable") from err
        return out["KeyId"], out["Plaintext"], out["CiphertextBlob"]

    def decrypt_data_key(self, key_id, encrypted_key, context):
        try:
            out = self._kms().decrypt(KeyId=key_id, CiphertextBlob=encrypted_key,
                                      EncryptionContext=context)
        except Exception as err:
            raise McpKeyUnavailable("key service unavailable") from err
        return out["Plaintext"]


_provider_override: Optional[KeyProvider] = None


def set_key_provider(provider: Optional[KeyProvider]) -> None:
    """Test/operator injection point; None restores the environment provider."""
    global _provider_override
    _provider_override = provider


def key_provider() -> KeyProvider:
    if _provider_override is not None:
        return _provider_override
    key_id = os.environ.get("Y_AGENT_MCP_KMS_KEY_ID", "").strip()
    if not key_id:
        raise McpKeyUnavailable("MCP credential key is not configured")
    return KmsKeyProvider(key_id)


def crypto_context(owner_public_id: str, connector_id: str, identity_generation: int,
                   kind: str) -> dict[str, str]:
    return {
        "deployment": os.environ.get("Y_AGENT_MCP_CRYPTO_CONTEXT", "y-agent"),
        "owner": owner_public_id,
        "connector": connector_id,
        "identity_generation": str(identity_generation),
        "kind": kind,
    }


def _aad(context: dict[str, str]) -> bytes:
    return json.dumps(context, sort_keys=True, separators=(",", ":")).encode()


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def seal(payload: dict, context: dict[str, str], provider: Optional[KeyProvider] = None) -> Envelope:
    provider = provider or key_provider()
    key_id, data_key, encrypted_key = provider.generate_data_key(context)
    nonce = os.urandom(12)
    ciphertext = AESGCM(data_key).encrypt(nonce, json.dumps(payload).encode(), _aad(context))
    return Envelope(key_id=key_id, encrypted_data_key=_b64(encrypted_key), nonce=_b64(nonce),
                    ciphertext=_b64(ciphertext))


def open_envelope(envelope: Envelope, context: dict[str, str],
                  provider: Optional[KeyProvider] = None) -> dict:
    provider = provider or key_provider()
    data_key = provider.decrypt_data_key(envelope.key_id, base64.b64decode(envelope.encrypted_data_key),
                                         context)
    try:
        raw = AESGCM(data_key).decrypt(base64.b64decode(envelope.nonce),
                                       base64.b64decode(envelope.ciphertext), _aad(context))
    except Exception as err:
        raise McpCiphertextInvalid("credential does not authenticate") from err
    return json.loads(raw)


def envelope_of(row) -> Envelope:
    return Envelope(key_id=row.key_id, encrypted_data_key=row.encrypted_data_key,
                    nonce=row.nonce, ciphertext=row.ciphertext)


def store_envelope(row, envelope: Envelope) -> None:
    row.key_id = envelope.key_id
    row.encrypted_data_key = envelope.encrypted_data_key
    row.nonce = envelope.nonce
    row.ciphertext = envelope.ciphertext
