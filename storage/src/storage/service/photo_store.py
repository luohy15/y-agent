"""Owner-bound private photo object store (todo 3838, host H1).

Callers pass an owner id plus an opaque id and a closed variant. The bucket,
key and URL are never caller input. Presigned POST pins checksum and exact
length for 300 seconds. Completion HEAD pins the object version. GET signs
only that version, with one bucket audit per batch of up to 100 ids. Delete
removes every version and delete marker under the id prefix and is idempotent.

The configured maintainer is required even when a module's dispatch scope is
authenticated. Unsafe bucket configuration is a hard deny, not a public fallback.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import uuid
from typing import Any, Optional

PHOTO_VARIANTS = ("original", "thumb", "display")
PHOTO_DERIVED_VARIANTS = ("thumb", "display")
PHOTO_MAX_BYTES = 200_000_000
PHOTO_URL_TTL_SECONDS = 300
PHOTO_URL_BATCH_MAX = 100
_PIN_MAX = 1024

_BLOCK = (
    "BlockPublicAcls",
    "BlockPublicPolicy",
    "IgnorePublicAcls",
    "RestrictPublicBuckets",
)


class PhotoStoreError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def bucket_name() -> str:
    value = os.environ.get("Y_AGENT_PHOTO_BUCKET")
    if not value:
        raise PhotoStoreError("Photo storage is unavailable.", "unavailable")
    return value


def allowed_origins() -> list[str]:
    raw = os.environ.get("Y_AGENT_PHOTO_CORS_ORIGINS") or ""
    origins = [part.strip() for part in raw.split(",") if part.strip()]
    if not origins or any(origin == "*" or "\n" in origin for origin in origins):
        raise PhotoStoreError("Photo CORS origins are not configured.", "forbidden")
    return origins


def s3_client():
    import boto3
    from botocore.config import Config

    return boto3.client("s3", config=Config(signature_version="s3v4"))


def _client(client):
    return client if client is not None else s3_client()


def validate_object_id(value: str) -> str:
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise PhotoStoreError("The photo id must be a canonical UUID.")
    return value


def validate_variant(variant: str, *, derived: bool = False) -> str:
    allowed = PHOTO_DERIVED_VARIANTS if derived else PHOTO_VARIANTS
    if variant not in allowed:
        raise PhotoStoreError("The photo variant is not allowed.")
    return variant


def validate_byte_count(byte_count) -> int:
    if type(byte_count) is not int or not 0 <= byte_count <= PHOTO_MAX_BYTES:
        raise PhotoStoreError(
            "Each file must be no larger than 200 MB (200,000,000 bytes)."
        )
    return byte_count


def validate_sha256_b64(checksum: str) -> str:
    try:
        digest = base64.b64decode(checksum, validate=True)
        if len(digest) != 32 or base64.b64encode(digest).decode("ascii") != checksum:
            raise ValueError()
    except (ValueError, binascii.Error):
        raise PhotoStoreError("The file checksum must be a Base64 SHA-256 digest.")
    return checksum


def validate_filename(filename: str) -> str:
    if (
        not filename
        or filename in {".", ".."}
        or any(char in filename for char in "/\\\0")
        or len(filename.encode("utf-8")) > 255
    ):
        raise PhotoStoreError("Choose a filename without separators and no longer than 255 bytes.")
    return filename


def validate_file_mtime(file_mtime: str) -> str:
    if not isinstance(file_mtime, str) or not file_mtime or len(file_mtime) > 64 or "\0" in file_mtime:
        raise PhotoStoreError("The file modified time must be an untrusted transfer fact.")
    return file_mtime


def audit_bucket_config(snapshot: dict, origins: list[str]) -> None:
    """Deny a bucket that is public, unversioned, unencrypted, or loosely CORS-open."""
    block = snapshot.get("public_access_block") or {}
    if any(block.get(key) is not True for key in _BLOCK):
        raise PhotoStoreError("Photo bucket public access is not blocked.", "forbidden")
    if snapshot.get("ownership") != "BucketOwnerEnforced":
        raise PhotoStoreError("Photo bucket ownership is not bucket-owner enforced.", "forbidden")
    if snapshot.get("versioning") != "Enabled":
        raise PhotoStoreError("Photo bucket versioning is not enabled.", "forbidden")
    if snapshot.get("encryption") is not True:
        raise PhotoStoreError("Photo bucket encryption is not enabled.", "forbidden")
    secure = False
    for statement in snapshot.get("policy_statements") or []:
        condition = ((statement.get("Condition") or {}).get("Bool") or {}).get("aws:SecureTransport")
        if statement.get("Effect") == "Deny" and condition in (False, "false"):
            secure = True
            break
    if not secure:
        raise PhotoStoreError("Photo bucket does not deny non-TLS access.", "forbidden")
    rules = snapshot.get("cors") or []
    if len(rules) != 1:
        raise PhotoStoreError("Photo bucket CORS is not the exact allowlist.", "forbidden")
    rule = rules[0]
    if rule.get("AllowedOrigins") != origins or "*" in (rule.get("AllowedOrigins") or []):
        raise PhotoStoreError("Photo bucket CORS origins are not the exact allowlist.", "forbidden")
    methods = set(rule.get("AllowedMethods") or [])
    if not methods or not methods <= {"GET", "HEAD", "POST"}:
        raise PhotoStoreError("Photo bucket CORS methods are not limited to read and POST.", "forbidden")


def _load_snapshot(client, bucket: str) -> dict:
    block = client.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
    ownership_rules = client.get_bucket_ownership_controls(Bucket=bucket)["OwnershipControls"]["Rules"]
    versioning = client.get_bucket_versioning(Bucket=bucket).get("Status")
    encryption_rules = client.get_bucket_encryption(Bucket=bucket)["ServerSideEncryptionConfiguration"]["Rules"]
    policy = json.loads(client.get_bucket_policy(Bucket=bucket)["Policy"])
    cors = client.get_bucket_cors(Bucket=bucket)["CORSRules"]
    return {
        "public_access_block": block,
        "ownership": ownership_rules[0].get("ObjectOwnership") if ownership_rules else None,
        "versioning": versioning,
        "encryption": bool(encryption_rules),
        "policy_statements": policy.get("Statement") or [],
        "cors": cors,
    }


def _require_owner(user_id: int) -> str:
    from storage.service.user import get_live_public_user_id, get_module_maintainer_user_id

    maintainer = get_module_maintainer_user_id()
    if maintainer is None or maintainer != user_id:
        raise PhotoStoreError(
            "Photo storage is restricted to the configured maintainer.", "forbidden"
        )
    public = get_live_public_user_id(user_id)
    if not isinstance(public, str) or not public or "/" in public or "\\" in public or ".." in public:
        raise PhotoStoreError("The photo owner was not found.", "forbidden")
    return public


def object_key(public_user_id: str, object_id: str, variant: str) -> str:
    return f"photos/{public_user_id}/{object_id}/{variant}"


def pin_key(public_user_id: str, object_id: str, variant: str) -> str:
    return f"photos/{public_user_id}/{object_id}/{variant}.pin"


def _absent(exc) -> bool:
    from botocore.exceptions import ClientError

    return isinstance(exc, ClientError) and exc.response.get("Error", {}).get("Code") in {
        "404", "NoSuchKey", "NoSuchVersion", "NotFound",
    }


def _read_pin(client, bucket: str, key: str) -> Optional[str]:
    try:
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as exc:
        if _absent(exc):
            return None
        raise
    text = body.decode("ascii").strip()
    return text or None


def _write_pin(client, bucket: str, key: str, version_id: str) -> str:
    existing = _read_pin(client, bucket, key)
    if existing is not None:
        if existing != version_id:
            raise PhotoStoreError("A ready photo cannot be overwritten.", "conflict")
        return existing
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=version_id.encode("ascii"),
            ContentType="text/plain",
            CacheControl="no-store",
            IfNoneMatch="*",
        )
    except Exception as exc:
        if not _absent(exc):
            raced = _read_pin(client, bucket, key)
            if raced == version_id:
                return raced
            if raced is not None:
                raise PhotoStoreError("A ready photo cannot be overwritten.", "conflict") from exc
        else:
            raise
    pinned = _read_pin(client, bucket, key)
    if pinned != version_id:
        raise PhotoStoreError("A ready photo cannot be overwritten.", "conflict")
    return version_id


def _presign_post(client, bucket: str, key: str, checksum: str, byte_count: int) -> dict:
    fields = {
        "x-amz-checksum-sha256": checksum,
        "x-amz-checksum-algorithm": "SHA256",
        "Cache-Control": "no-store",
    }
    return client.generate_presigned_post(
        Bucket=bucket,
        Key=key,
        Fields=fields,
        Conditions=[{name: value} for name, value in fields.items()]
        + [["content-length-range", byte_count, byte_count]],
        ExpiresIn=PHOTO_URL_TTL_SECONDS,
    )


def _guard(client, bucket: str) -> None:
    audit_bucket_config(_load_snapshot(client, bucket), allowed_origins())


def authorize_upload(
    user_id: int,
    upload_id: str,
    *,
    sha256_b64: str,
    byte_count: int,
    filename: str,
    file_mtime: str,
    client=None,
) -> dict[str, Any]:
    """Presign a POST for a new original. file_mtime is an untrusted transfer fact."""
    public = _require_owner(user_id)
    upload_id = validate_object_id(upload_id)
    checksum = validate_sha256_b64(sha256_b64)
    size = validate_byte_count(byte_count)
    filename = validate_filename(filename)
    file_mtime = validate_file_mtime(file_mtime)
    s3 = _client(client)
    name = bucket_name()
    _guard(s3, name)
    key = object_key(public, upload_id, "original")
    if _read_pin(s3, name, pin_key(public, upload_id, "original")) is not None:
        raise PhotoStoreError("A ready photo cannot be overwritten.", "conflict")
    post = _presign_post(s3, name, key, checksum, size)
    return {
        "upload_id": upload_id,
        "variant": "original",
        "post": post,
        "expires_in": PHOTO_URL_TTL_SECONDS,
        "cache_control": "no-store",
        "filename": filename,
        "file_mtime": file_mtime,
        "byte_count": size,
    }


def authorize_derived_upload(
    user_id: int,
    photo_id: str,
    *,
    variant: str,
    sha256_b64: str,
    byte_count: int,
    client=None,
) -> dict[str, Any]:
    """Presign a POST for thumb or display after the original version is pinned."""
    public = _require_owner(user_id)
    photo_id = validate_object_id(photo_id)
    variant = validate_variant(variant, derived=True)
    checksum = validate_sha256_b64(sha256_b64)
    size = validate_byte_count(byte_count)
    s3 = _client(client)
    name = bucket_name()
    _guard(s3, name)
    if _read_pin(s3, name, pin_key(public, photo_id, "original")) is None:
        raise PhotoStoreError("The original photo is not pinned.", "not_found")
    if _read_pin(s3, name, pin_key(public, photo_id, variant)) is not None:
        raise PhotoStoreError("A ready photo cannot be overwritten.", "conflict")
    post = _presign_post(s3, name, object_key(public, photo_id, variant), checksum, size)
    return {
        "photo_id": photo_id,
        "variant": variant,
        "post": post,
        "expires_in": PHOTO_URL_TTL_SECONDS,
        "cache_control": "no-store",
        "byte_count": size,
    }


def verify_and_pin(
    user_id: int,
    object_id: str,
    *,
    variant: str = "original",
    sha256_b64: str,
    byte_count: int,
    client=None,
) -> dict[str, Any]:
    """HEAD the latest object, require size and checksum, pin that version."""
    public = _require_owner(user_id)
    object_id = validate_object_id(object_id)
    variant = validate_variant(variant)
    checksum = validate_sha256_b64(sha256_b64)
    size = validate_byte_count(byte_count)
    s3 = _client(client)
    name = bucket_name()
    _guard(s3, name)
    key = object_key(public, object_id, variant)
    try:
        head = s3.head_object(Bucket=name, Key=key, ChecksumMode="ENABLED")
    except Exception as exc:
        if _absent(exc):
            raise PhotoStoreError("The uploaded object was not found.") from exc
        raise
    version_id = head.get("VersionId")
    if (
        not version_id
        or head.get("ContentLength") != size
        or head.get("ChecksumSHA256") != checksum
    ):
        raise PhotoStoreError("The uploaded object did not match the declared size and checksum.")
    pinned = _write_pin(s3, name, pin_key(public, object_id, variant), version_id)
    return {
        "id": object_id,
        "variant": variant,
        "version_id": pinned,
        "byte_count": size,
        "cache_control": "no-store",
    }


def validate_object_ids(photo_ids) -> list[str]:
    """A list of at most 100 distinct canonical UUIDs, in caller order."""
    if not isinstance(photo_ids, list) or len(photo_ids) > PHOTO_URL_BATCH_MAX:
        raise PhotoStoreError(f"Photo ids must be a list of at most {PHOTO_URL_BATCH_MAX}.")
    checked = [validate_object_id(photo_id) for photo_id in photo_ids]
    if len(set(checked)) != len(checked):
        raise PhotoStoreError("Photo ids must not repeat.")
    return checked


def _read_version_pin(client, bucket: str, key: str) -> Optional[str]:
    """Pinned version id, None only when the pin object is absent. A malformed pin is an error."""
    try:
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as exc:
        if _absent(exc):
            return None
        raise
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError:
        text = ""
    if not text or len(text) > _PIN_MAX or any(char.isspace() or not char.isprintable() for char in text):
        raise PhotoStoreError("The photo pin is unreadable.", "unavailable")
    return text


def authorize_get_batch(
    user_id: int,
    photo_ids: list[str],
    *,
    variant: str,
    client=None,
) -> dict[str, Any]:
    """Sign 300s GETs for the pinned versions of up to 100 ids, auditing the bucket once.

    Order follows the input. Only an absent pin lands in missing; config,
    transport and malformed-pin failures fail the whole call.
    """
    public = _require_owner(user_id)
    photo_ids = validate_object_ids(photo_ids)
    variant = validate_variant(variant)
    data: list[dict[str, Any]] = []
    missing: list[str] = []
    if not photo_ids:
        return {"data": data, "missing": missing}
    s3 = _client(client)
    name = bucket_name()
    _guard(s3, name)
    for photo_id in photo_ids:
        version_id = _read_version_pin(s3, name, pin_key(public, photo_id, variant))
        if version_id is None:
            missing.append(photo_id)
            continue
        url = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": name,
                "Key": object_key(public, photo_id, variant),
                "VersionId": version_id,
                "ResponseCacheControl": "no-store",
            },
            ExpiresIn=PHOTO_URL_TTL_SECONDS,
        )
        data.append({
            "photo_id": photo_id,
            "variant": variant,
            "url": url,
            "expires_in": PHOTO_URL_TTL_SECONDS,
            "cache_control": "no-store",
        })
    return {"data": data, "missing": missing}


def authorize_get(
    user_id: int,
    photo_id: str,
    *,
    variant: str,
    client=None,
) -> dict[str, Any]:
    """Sign a GET for the pinned version only."""
    signed = authorize_get_batch(user_id, [photo_id], variant=variant, client=client)
    if not signed["data"]:
        raise PhotoStoreError("The photo object is not pinned.", "not_found")
    return signed["data"][0]


def delete_all_versions(user_id: int, photo_id: str, *, client=None) -> dict[str, Any]:
    """Delete every version and delete marker for this id. A second call is success."""
    public = _require_owner(user_id)
    photo_id = validate_object_id(photo_id)
    s3 = _client(client)
    name = bucket_name()
    _guard(s3, name)
    prefix = f"photos/{public}/{photo_id}/"
    token = None
    targets = []
    while True:
        kwargs = {"Bucket": name, "Prefix": prefix}
        if token:
            kwargs["KeyMarker"] = token["KeyMarker"]
            kwargs["VersionIdMarker"] = token["VersionIdMarker"]
        page = s3.list_object_versions(**kwargs)
        for row in page.get("Versions") or []:
            if row["Key"].startswith(prefix):
                targets.append({"Key": row["Key"], "VersionId": row["VersionId"]})
        for row in page.get("DeleteMarkers") or []:
            if row["Key"].startswith(prefix):
                targets.append({"Key": row["Key"], "VersionId": row["VersionId"]})
        if not page.get("IsTruncated"):
            break
        token = {
            "KeyMarker": page.get("NextKeyMarker"),
            "VersionIdMarker": page.get("NextVersionIdMarker"),
        }
    deleted = 0
    for start in range(0, len(targets), 1000):
        chunk = targets[start:start + 1000]
        if not chunk:
            continue
        result = s3.delete_objects(Bucket=name, Delete={"Objects": chunk, "Quiet": True})
        errors = result.get("Errors") or []
        if errors:
            raise PhotoStoreError("Photo object deletion did not finish.", "unavailable")
        deleted += len(chunk)
    return {"photo_id": photo_id, "deleted": deleted, "cache_control": "no-store"}
