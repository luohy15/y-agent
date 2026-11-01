"""Private, owner-bound voice objects in the existing content bucket (todo 4165)."""

from __future__ import annotations

import base64
import hashlib
import os
import uuid
from typing import Any

VOICE_MAX_BYTES = 4_000_000
VOICE_MAX_DURATION_MS = 120_000
_BLOCK = ("BlockPublicAcls", "BlockPublicPolicy", "IgnorePublicAcls", "RestrictPublicBuckets")


class VoiceStoreError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def _require_owner(user_id: int) -> str:
    from storage.service.user import get_live_public_user_id, get_module_maintainer_user_id

    maintainer = get_module_maintainer_user_id()
    if maintainer is None or maintainer != user_id:
        raise VoiceStoreError("Voice storage is restricted to the configured maintainer.", "forbidden")
    public = get_live_public_user_id(user_id)
    if not isinstance(public, str) or not public or any(part in public for part in ("/", "\\", "..")):
        raise VoiceStoreError("The voice owner was not found.", "forbidden")
    return public


def _object_prefix(user_id: int, take_id: str) -> str:
    public = _require_owner(user_id)
    try:
        if str(uuid.UUID(take_id)) != take_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as exc:
        raise VoiceStoreError("The take id must be a canonical UUID.") from exc
    return f"voice/{public}/{take_id}/"


def _validate_upload(data: bytes, duration_ms: int) -> None:
    if not isinstance(data, bytes) or not 12 <= len(data) <= VOICE_MAX_BYTES:
        raise VoiceStoreError("Each WAV must contain 12 to 4,000,000 bytes.")
    if type(duration_ms) is not int or not 0 < duration_ms <= VOICE_MAX_DURATION_MS:
        raise VoiceStoreError("Each take must last between 1 and 120,000 milliseconds.")
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise VoiceStoreError("The uploaded take must have a RIFF/WAVE header.")


def _store(client):
    name = os.environ.get("Y_AGENT_S3_BUCKET")
    if not name:
        raise VoiceStoreError("Voice storage is unavailable.", "unavailable")
    if client is None:
        import boto3
        from botocore.config import Config

        client = boto3.client("s3", config=Config(signature_version="s3v4"))
    block = client.get_public_access_block(Bucket=name).get("PublicAccessBlockConfiguration", {})
    if any(block.get(key) is not True for key in _BLOCK):
        raise VoiceStoreError("Voice bucket public access is not blocked.", "forbidden")
    if client.get_bucket_versioning(Bucket=name).get("Status") != "Enabled":
        raise VoiceStoreError("Voice bucket versioning is not enabled.", "forbidden")
    rules = client.get_bucket_encryption(Bucket=name).get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
    if not any(rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm") in
               ("AES256", "aws:kms", "aws:kms:dsse") for rule in rules):
        raise VoiceStoreError("Voice bucket encryption is not enabled.", "forbidden")
    return client, name


def _error_code(exc) -> str | None:
    from botocore.exceptions import ClientError

    if isinstance(exc, ClientError):
        return exc.response.get("Error", {}).get("Code")
    return None


def _validate_version(version_id: str) -> None:
    if (not isinstance(version_id, str) or not version_id or version_id == "null"
            or len(version_id) > 1024 or any(c.isspace() or not c.isprintable() for c in version_id)):
        raise VoiceStoreError("A pinned object version is required.")


def put_object(
    user_id: int, take_id: str, *, data: bytes, duration_ms: int, client=None,
) -> dict[str, Any]:
    """Write a validated WAV; the module persists the returned immutable version."""
    prefix = _object_prefix(user_id, take_id)
    _validate_upload(data, duration_ms)
    s3, bucket = _store(client)
    digest = hashlib.sha256(data)
    result = s3.put_object(
        Bucket=bucket, Key=prefix + "original", Body=data,
        ContentType="audio/wav", CacheControl="no-store",
        ChecksumSHA256=base64.b64encode(digest.digest()).decode("ascii"),
    )
    version = result.get("VersionId")
    try:
        _validate_version(version)
    except VoiceStoreError as exc:
        raise VoiceStoreError("Voice storage did not return an immutable version.", "unavailable") from exc
    return {"id": take_id, "version_id": version, "byte_count": len(data),
            "sha256": digest.hexdigest(), "cache_control": "no-store"}


def get_object(user_id: int, take_id: str, *, version_id: str, client=None) -> bytes:
    """Read only the module's pinned version, never the current object implicitly."""
    prefix = _object_prefix(user_id, take_id)
    _validate_version(version_id)
    s3, bucket = _store(client)
    try:
        result = s3.get_object(Bucket=bucket, Key=prefix + "original", VersionId=version_id)
    except Exception as exc:
        if _error_code(exc) in {"404", "NoSuchKey", "NoSuchVersion", "NotFound"}:
            raise VoiceStoreError("The voice object was not found.", "not_found") from exc
        raise
    body = result["Body"]
    try:
        data = body.read(VOICE_MAX_BYTES + 1)
    finally:
        body.close()
    if len(data) > VOICE_MAX_BYTES:
        raise VoiceStoreError("The stored voice object exceeds the byte limit.", "unavailable")
    return data


def delete_all_versions(user_id: int, take_id: str, *, client=None) -> dict[str, Any]:
    """Remove every object version and delete marker in this take's prefix."""
    prefix = _object_prefix(user_id, take_id)
    s3, bucket = _store(client)
    params = {"Bucket": bucket, "Prefix": prefix}
    targets = []
    while True:
        page = s3.list_object_versions(**params)
        for row in (page.get("Versions") or []) + (page.get("DeleteMarkers") or []):
            if row["Key"].startswith(prefix):
                targets.append({"Key": row["Key"], "VersionId": row["VersionId"]})
        if not page.get("IsTruncated"):
            break
        params["KeyMarker"] = page["NextKeyMarker"]
        params["VersionIdMarker"] = page["NextVersionIdMarker"]
    for start in range(0, len(targets), 1000):
        result = s3.delete_objects(Bucket=bucket, Delete={"Objects": targets[start:start + 1000], "Quiet": True})
        if result.get("Errors"):
            raise VoiceStoreError("Voice object deletion did not finish.", "unavailable")
    return {"id": take_id, "deleted": len(targets), "cache_control": "no-store"}
