"""Upload authorization, public status and staging transport."""

import base64
import binascii
import json
import os
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from storage.repository import upload_job as repo
from storage.service import vm_config
from storage.upload_timing import POST_TTL_MS, POST_TTL_SECONDS
from storage.util import get_unix_timestamp

MAX_SIZE_BYTES = 20_000_000
DID_NOT_FINISH = "The upload did not finish. Select the file again."
STAGED_EXPIRED = "The staged copy expired. Select the file again."
ATTEMPTS_EXHAUSTED = "The transfer did not complete after 5 attempts."
DESTINATION_CHANGED = "The destination already exists. Select the file again and confirm overwrite."
NOT_A_DIRECTORY = "The upload destination is not a directory. Select another directory."


class UploadError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def bucket():
    value = os.environ.get("Y_AGENT_UPLOAD_BUCKET")
    if not value:
        raise UploadError("File uploads are unavailable.", 503)
    return value


def s3_client():
    return boto3.client("s3", config=Config(signature_version="s3v4"))


def enqueue(row):
    boto3.client("sqs").send_message(
        QueueUrl=os.environ["Y_AGENT_UPLOAD_QUEUE_URL"],
        MessageBody=json.dumps({"upload_id": row["upload_id"], "staging_key": row["staging_key"]}),
        DelaySeconds=30 if row["attempts"] else 0,
    )


def is_absent(exc):
    return isinstance(exc, ClientError) and exc.response.get("Error", {}).get("Code") in {
        "404", "NoSuchKey", "NoSuchVersion", "NotFound"}


def head_version(client, row, version=None):
    return client.head_object(Bucket=bucket(), Key=row["staging_key"],
                              VersionId=version or row["staging_version_id"], ChecksumMode="ENABLED")


def valid_head(row, head):
    return (head.get("ContentLength") == row["size_bytes"] and
            head.get("ChecksumSHA256") == row["expected_checksum_sha256_b64"])


def validate_batch_id(value):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise UploadError("The upload batch ID must be a canonical UUID.")
    return value


def resolve_owner(public_user_id):
    owner = repo.owner_id(public_user_id)
    if owner is None:
        raise UploadError("The upload owner was not found.", 404)
    return owner


def authorize(public_user_id, *, batch_id, filename, size_bytes, checksum_sha256_b64,
              dest_dir, vm_name="default", work_dir=None, overwrite_ack=False):
    validate_batch_id(batch_id)
    if (not filename or filename in {".", ".."} or any(c in filename for c in "/\\\0")
            or len(filename.encode("utf-8")) > 255):
        raise UploadError("Choose a filename without separators and no longer than 255 bytes.")
    if type(size_bytes) is not int or not 0 <= size_bytes <= MAX_SIZE_BYTES:
        raise UploadError("Each file must be no larger than 20 MB (20,000,000 bytes).")
    try:
        digest = base64.b64decode(checksum_sha256_b64, validate=True)
        if len(digest) != 32 or base64.b64encode(digest).decode() != checksum_sha256_b64:
            raise ValueError()
    except (ValueError, binascii.Error):
        raise UploadError("The file checksum must be a Base64 SHA-256 digest.")
    if not dest_dir or "\0" in dest_dir or (work_dir is not None and "\0" in work_dir):
        raise UploadError("Choose a valid upload destination directory.")
    owner = resolve_owner(public_user_id)
    vm = vm_config.get_config(owner, vm_name)
    if vm is None:
        raise UploadError("No upload VM is configured for your account.", 404)
    upload_id = str(uuid.uuid4())
    key = f"uploads/{public_user_id}/{upload_id}"
    fields = {"x-amz-checksum-sha256": checksum_sha256_b64, "x-amz-checksum-algorithm": "SHA256"}
    try:
        post = s3_client().generate_presigned_post(
            Bucket=bucket(), Key=key, Fields=fields,
            Conditions=[{k: v} for k, v in fields.items()] + [["content-length-range", size_bytes, size_bytes]],
            ExpiresIn=POST_TTL_SECONDS)
    except UploadError:
        raise
    except Exception:
        raise UploadError("Upload authorization failed. Try again.", 503)
    row = repo.create(owner, upload_id=upload_id, batch_id=batch_id, vm_name=vm_name,
                      work_dir=work_dir if work_dir is not None else (vm.work_dir or ""),
                      dest_dir=dest_dir, filename=filename, size_bytes=size_bytes,
                      expected_checksum_sha256_b64=checksum_sha256_b64, staging_key=key,
                      overwrite_ack=overwrite_ack)
    return {"job": public_job(row), "post": post, "expires_at_unix": row["created_at_unix"] + POST_TTL_MS,
            "max_size_bytes": MAX_SIZE_BYTES}


def public_job(row):
    status, error = row["status"], row["error"]
    return {
        **{key: row[key] for key in ("upload_id", "batch_id", "vm_name", "work_dir", "dest_dir", "filename",
                                    "size_bytes", "created_at_unix", "updated_at_unix", "saved_at")},
        "state": {"authorized": "uploading", "staged": "waiting"}.get(status, status),
        "error": error,
        "retryable": status == "failed" and bool(row["staging_version_id"]) and error not in {
            DID_NOT_FINISH, STAGED_EXPIRED, DESTINATION_CHANGED, NOT_A_DIRECTORY},
    }


def get_batch(public_user_id, batch_id):
    validate_batch_id(batch_id)
    rows = repo.batch(resolve_owner(public_user_id), batch_id)
    if not rows:
        raise UploadError("The upload batch was not found.", 404)
    return {"batch_id": batch_id, "jobs": [public_job(row) for row in rows]}


def get_active(public_user_id):
    batches = {}
    for row in repo.active(resolve_owner(public_user_id)):
        batches.setdefault(row["batch_id"], []).append(public_job(row))
    return {"batches": [{"batch_id": key, "jobs": jobs} for key, jobs in batches.items()]}


def retry_upload(public_user_id, upload_id):
    owner = resolve_owner(public_user_id)
    row = repo.get(owner, upload_id)
    if not row:
        raise UploadError("The upload was not found.", 404)
    if row["status"] != "failed":
        raise UploadError("Only a failed upload can be retried.", 409)
    if not public_job(row)["retryable"]:
        raise UploadError(row["error"] or STAGED_EXPIRED, 409)
    try:
        head = head_version(s3_client(), row)
    except Exception as exc:
        if is_absent(exc):
            raise UploadError(STAGED_EXPIRED, 409)
        raise UploadError("The staged copy could not be checked. Try again shortly.", 503)
    if not valid_head(row, head):
        raise UploadError("The staged copy failed verification. Select the file again.", 409)
    row = repo.retry(owner, upload_id, get_unix_timestamp())
    if not row:
        raise UploadError("The upload state changed. Refresh its status.", 409)
    try:
        enqueue(row)
    except Exception:
        # The scheduled sweep repairs the DB/SQS handoff gap.
        pass
    return {"job": public_job(row)}


# The worker uses the same service boundary; state transitions remain single SQL statements.
get = repo.get
promote = repo.promote
claim = repo.claim
finish_attempt = repo.finish_attempt
recovery_candidates = repo.recovery_candidates
recover = repo.recover
