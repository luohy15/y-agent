"""Private, owner-bound voice objects in the existing content bucket (todo 4165)."""

from __future__ import annotations

import base64
import hashlib
import os
import struct
import threading
import time
import uuid
from typing import Any

VOICE_MAX_BYTES = 4_000_000
VOICE_MAX_DURATION_MS = 120_000
VOICE_MAX_PART_BYTES = 1_000_000
VOICE_MAX_PARTS = 300
_AUDIO_FORMATS = {"wav": "audio/wav", "pcm": "application/octet-stream"}
_WAV_HEADER_BYTES = 44
_BUCKET_AUDIT_TTL = 60
_bucket_audits: dict[str, float] = {}
_audit_lock = threading.Lock()
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


def _validate_format(audio_format: str) -> None:
    if not isinstance(audio_format, str) or audio_format not in _AUDIO_FORMATS:
        raise VoiceStoreError("The audio format is unsupported.")


def _assemble_wav(data: bytes, audio_format: str) -> bytes:
    if audio_format == "pcm":
        if len(data) % 2:
            raise VoiceStoreError("PCM16 audio must contain whole samples.")
        data = struct.pack(
            "<4sI4s4sIHHIIHH4sI", b"RIFF", len(data) + 36, b"WAVE", b"fmt ",
            16, 1, 1, 16_000, 32_000, 2, 16, b"data", len(data),
        ) + data
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise VoiceStoreError("The audio must have a RIFF/WAVE header.")
    return data


def _parts_prefix(prefix: str) -> str:
    return prefix.replace("voice/", "voice-parts/", 1)


def _store(client):
    name = os.environ.get("Y_AGENT_S3_BUCKET")
    if not name:
        raise VoiceStoreError("Voice storage is unavailable.", "unavailable")
    if client is None:
        import boto3
        from botocore.config import Config

        client = boto3.client("s3", config=Config(signature_version="s3v4"))
    with _audit_lock:
        if time.monotonic() >= _bucket_audits.get(name, 0):
            _bucket_audits.pop(name, None)
            block = client.get_public_access_block(Bucket=name).get("PublicAccessBlockConfiguration", {})
            if any(block.get(key) is not True for key in _BLOCK):
                raise VoiceStoreError("Voice bucket public access is not blocked.", "forbidden")
            if client.get_bucket_versioning(Bucket=name).get("Status") != "Enabled":
                raise VoiceStoreError("Voice bucket versioning is not enabled.", "forbidden")
            rules = client.get_bucket_encryption(Bucket=name).get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
            if not any(rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm") in
                       ("AES256", "aws:kms", "aws:kms:dsse") for rule in rules):
                raise VoiceStoreError("Voice bucket encryption is not enabled.", "forbidden")
            _bucket_audits[name] = time.monotonic() + _BUCKET_AUDIT_TTL
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


def _head(s3, bucket: str, key: str):
    try:
        return s3.head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        if _error_code(exc) in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise


def _part_metadata(head, audio_format: str) -> dict[str, Any]:
    meta = head.get("Metadata", {})
    if meta.get("audio_format") != audio_format:
        raise VoiceStoreError("Parts must have the same audio format.")
    try:
        offset, size = int(meta["offset"]), int(meta["byte_count"])
        digest = meta["sha256"]
        if offset < 0 or not 1 <= size <= VOICE_MAX_PART_BYTES or size != head["ContentLength"]:
            raise ValueError()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError()
        _validate_version(head.get("VersionId"))
    except (KeyError, TypeError, ValueError, VoiceStoreError) as exc:
        raise VoiceStoreError("Stored part metadata is invalid.", "unavailable") from exc
    return {"offset": offset, "byte_count": size, "sha256": digest}


def put_part(
    user_id: int, take_id: str, index: int, offset: int, *, data: bytes,
    audio_format: str, client=None,
) -> dict[str, Any]:
    """Append an immutable ordered part, or acknowledge an identical retry."""
    prefix = _parts_prefix(_object_prefix(user_id, take_id))
    _validate_format(audio_format)
    if type(index) is not int or not 0 <= index < VOICE_MAX_PARTS:
        raise VoiceStoreError("The part index is invalid.")
    if type(offset) is not int or offset < 0:
        raise VoiceStoreError("The part offset is invalid.")
    if not isinstance(data, bytes) or not 1 <= len(data) <= VOICE_MAX_PART_BYTES:
        raise VoiceStoreError("Each part must contain 1 to 1,000,000 bytes.")
    if audio_format == "pcm" and len(data) % 2:
        raise VoiceStoreError("PCM16 parts must contain whole samples.")
    s3, bucket = _store(client)
    expected_offset = 0
    if index:
        previous = _head(s3, bucket, prefix + f"{index - 1:06d}")
        if previous is None:
            raise VoiceStoreError("The previous part is missing.", "conflict")
        previous = _part_metadata(previous, audio_format)
        expected_offset = previous["offset"] + previous["byte_count"]
    if offset != expected_offset:
        raise VoiceStoreError("The part offset is not contiguous.", "conflict")
    digest = hashlib.sha256(data)
    metadata = {"offset": str(offset), "byte_count": str(len(data)),
                "sha256": digest.hexdigest(), "audio_format": audio_format}
    key = prefix + f"{index:06d}"
    existing = _head(s3, bucket, key)
    if existing is None:
        try:
            s3.put_object(
                Bucket=bucket, Key=key, Body=data, IfNoneMatch="*",
                ContentType=_AUDIO_FORMATS[audio_format], CacheControl="no-store",
                ChecksumSHA256=base64.b64encode(digest.digest()).decode("ascii"), Metadata=metadata,
            )
        except Exception as exc:
            if _error_code(exc) not in {"PreconditionFailed", "412", "ConditionalRequestConflict", "409"}:
                raise
            existing = _head(s3, bucket, key)
            if existing is None:
                raise VoiceStoreError("The part changed concurrently; retry it.", "conflict") from exc
    if existing is not None:
        prior = _part_metadata(existing, audio_format)
        if prior != {"offset": offset, "byte_count": len(data), "sha256": digest.hexdigest()}:
            raise VoiceStoreError("The part already contains different bytes.", "conflict")
    return {"id": take_id, "index": index, "offset": offset, "byte_count": len(data),
            "sha256": digest.hexdigest(), "duplicate": existing is not None}


def _final_result(take_id: str, head) -> dict[str, Any]:
    meta = head.get("Metadata", {})
    try:
        _validate_version(head.get("VersionId"))
        if meta["audio_format"] != "wav":
            raise ValueError()
        size = int(meta["byte_count"])
        count = int(meta["part_count"])
        digest = meta["sha256"]
        if not 1 <= size <= VOICE_MAX_BYTES or size != head["ContentLength"] or not 1 <= count <= VOICE_MAX_PARTS:
            raise ValueError()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError()
    except (KeyError, TypeError, ValueError, VoiceStoreError) as exc:
        raise VoiceStoreError("Stored voice metadata is invalid.", "unavailable") from exc
    return {"id": take_id, "version_id": head["VersionId"], "byte_count": size,
            "sha256": digest, "audio_format": meta["audio_format"]}


def _cleanup_parts(s3, bucket: str, prefix: str) -> None:
    try:
        _delete_prefix(s3, bucket, prefix)
    except Exception:
        # A committed original must remain successful; lifecycle removes leftovers.
        pass


def finalize_parts(
    user_id: int, take_id: str, *, part_count: int, audio_format: str,
    duration_ms: int, client=None,
) -> dict[str, Any]:
    """Assemble a bounded take once; replay returns the committed pinned version."""
    prefix = _object_prefix(user_id, take_id)
    parts = _parts_prefix(prefix)
    _validate_format(audio_format)
    if type(part_count) is not int or not 1 <= part_count <= VOICE_MAX_PARTS:
        raise VoiceStoreError("The part count is invalid.")
    if type(duration_ms) is not int or not 1 <= duration_ms <= VOICE_MAX_DURATION_MS:
        raise VoiceStoreError("Each take must last between 1 and 120,000 milliseconds.")
    s3, bucket = _store(client)
    existing = _head(s3, bucket, prefix + "original")
    if existing is not None:
        result = _final_result(take_id, existing)
        _cleanup_parts(s3, bucket, parts)
        return result
    keys = set()
    params = {"Bucket": bucket, "Prefix": parts}
    while True:
        page = s3.list_objects_v2(**params)
        keys.update(row["Key"] for row in page.get("Contents", []))
        if len(keys) > part_count:
            raise VoiceStoreError("Unexpected parts were uploaded.", "conflict")
        if not page.get("IsTruncated"):
            break
        params["ContinuationToken"] = page["NextContinuationToken"]
    ordered = [parts + f"{index:06d}" for index in range(part_count)]
    if keys != set(ordered):
        raise VoiceStoreError("The uploaded part set is incomplete.", "conflict")
    total = 0
    byte_limit = VOICE_MAX_BYTES - _WAV_HEADER_BYTES if audio_format == "pcm" else VOICE_MAX_BYTES
    manifest = []
    for key in ordered:
        head = _head(s3, bucket, key)
        if head is None:
            raise VoiceStoreError("An uploaded part is missing.", "conflict")
        meta = _part_metadata(head, audio_format)
        if meta["offset"] != total:
            raise VoiceStoreError("The part offsets are not contiguous.", "conflict")
        total += meta["byte_count"]
        if total > byte_limit:
            raise VoiceStoreError("The assembled WAV exceeds 4,000,000 bytes.", "too_large")
        manifest.append((key, head["VersionId"], meta))
    chunks = []
    for key, version, meta in manifest:
        stored = s3.get_object(Bucket=bucket, Key=key, VersionId=version)
        body = stored["Body"]
        try:
            chunk = body.read(meta["byte_count"] + 1)
        finally:
            body.close()
        if len(chunk) != meta["byte_count"] or hashlib.sha256(chunk).hexdigest() != meta["sha256"]:
            raise VoiceStoreError("Stored part bytes do not match metadata.", "unavailable")
        chunks.append(chunk)
    data = _assemble_wav(b"".join(chunks), audio_format)
    digest = hashlib.sha256(data)
    metadata = {"sha256": digest.hexdigest(), "byte_count": str(len(data)),
                "audio_format": "wav", "part_count": str(part_count)}
    try:
        written = s3.put_object(
            Bucket=bucket, Key=prefix + "original", Body=data, IfNoneMatch="*",
            ContentType="audio/wav", CacheControl="no-store",
            ChecksumSHA256=base64.b64encode(digest.digest()).decode("ascii"), Metadata=metadata,
        )
        result = _final_result(take_id, {**written, "Metadata": metadata, "ContentLength": len(data)})
    except Exception as exc:
        if _error_code(exc) not in {"PreconditionFailed", "412", "ConditionalRequestConflict", "409"}:
            raise
        existing = _head(s3, bucket, prefix + "original")
        if existing is None:
            raise VoiceStoreError("The take changed concurrently; retry finalize.", "conflict") from exc
        result = _final_result(take_id, existing)
    _cleanup_parts(s3, bucket, parts)
    return result


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


def delete_parts(user_id: int, take_id: str, *, client=None) -> dict[str, Any]:
    """Remove all transient part versions and markers, including abandoned takes."""
    prefix = _parts_prefix(_object_prefix(user_id, take_id))
    s3, bucket = _store(client)
    return {"id": take_id, "deleted": _delete_prefix(s3, bucket, prefix)}


def delete_all_versions(user_id: int, take_id: str, *, client=None) -> dict[str, Any]:
    """Remove every original and transient part version and delete marker."""
    prefix = _object_prefix(user_id, take_id)
    s3, bucket = _store(client)
    deleted = _delete_prefix(s3, bucket, prefix) + _delete_prefix(s3, bucket, _parts_prefix(prefix))
    return {"id": take_id, "deleted": deleted, "cache_control": "no-store"}


def _delete_prefix(s3, bucket: str, prefix: str) -> int:
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
    return len(targets)
