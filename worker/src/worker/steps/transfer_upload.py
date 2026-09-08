"""Version-pinned S3 completion and fenced VM delivery."""

import json
import uuid
from urllib.parse import unquote_plus

from loguru import logger
from agent.vm_command import execute_vm_command
from storage.service import upload_job as uploads, vm_config
from storage.util import get_unix_timestamp
from worker.steps.upload_placement import PLACEMENT_SCRIPT


def job_for_key(key):
    parts = key.split("/")
    if len(parts) != 3 or parts[0] != "uploads":
        return None
    try:
        owner = uploads.resolve_owner(parts[1])
    except uploads.UploadError:
        return None
    row = uploads.get(owner, parts[2])
    return row if row and row["staging_key"] == key else None


def discard_unpinned(client, row, version):
    current = uploads.get(row["user_id"], row["upload_id"])
    if current and current["staging_version_id"] and current["staging_version_id"] != version:
        try:
            client.delete_object(Bucket=uploads.bucket(), Key=row["staging_key"], VersionId=version)
        except Exception:
            logger.warning("[upload] surplus version cleanup deferred upload={}", row["upload_id"])


def process_s3_event(record):
    obj = record.get("s3", {})
    if obj.get("bucket", {}).get("name") != uploads.bucket():
        return
    key = unquote_plus(obj.get("object", {}).get("key", ""))
    version = obj.get("object", {}).get("versionId")
    row = job_for_key(key)
    if not row or not version or version == row["staging_version_id"]:
        return
    client = uploads.s3_client()
    try:
        valid = uploads.valid_head(row, uploads.head_version(client, row, version))
    except Exception:
        discard_unpinned(client, row, version)
        raise
    if not valid:
        discard_unpinned(client, row, version)
        return
    promoted = uploads.promote(row["user_id"], row["upload_id"], version, get_unix_timestamp())
    if promoted:
        uploads.enqueue(promoted)
    else:
        discard_unpinned(client, row, version)


def cleanup_saved(client, row):
    current = uploads.get(row["user_id"], row["upload_id"])
    if (current and current["status"] == "saved" and
            current["staging_version_id"] == row["staging_version_id"]):
        try:
            client.delete_object(Bucket=uploads.bucket(), Key=row["staging_key"],
                                 VersionId=row["staging_version_id"])
        except Exception:
            logger.warning("[upload] saved version cleanup deferred upload={}", row["upload_id"])


async def transfer_upload(row):
    token = str(uuid.uuid4())
    row = uploads.claim(row["user_id"], row["upload_id"], token, get_unix_timestamp())
    if not row:
        return
    try:
        client = uploads.s3_client()
        vm = vm_config.get_config(row["user_id"], row["vm_name"])
        if vm is None:
            raise RuntimeError("VM unavailable")
        await execute_vm_command(vm, ["true"], timeout=15, work_dir=row["work_dir"], check=True)
        url = client.generate_presigned_url("get_object", Params={
            "Bucket": uploads.bucket(), "Key": row["staging_key"], "VersionId": row["staging_version_id"],
        }, ExpiresIn=600)
        inputs = {key: row[key] for key in ("upload_id", "lease_token", "dest_dir", "filename", "size_bytes",
                                           "expected_checksum_sha256_b64", "overwrite_ack")}
        inputs["url"] = url
        output = await execute_vm_command(vm, ["python3", "-c", PLACEMENT_SCRIPT],
                                          stdin=json.dumps(inputs), timeout=300,
                                          work_dir=row["work_dir"], check=True)
        result = json.loads(output)["result"]
        if result in {"saved", "already_placed"}:
            saved = uploads.finish_attempt(row["user_id"], row["upload_id"], token, "saved")
            if saved:
                cleanup_saved(client, saved)
            return
        if result in {"destination_changed", "not_a_directory"}:
            error = uploads.DESTINATION_CHANGED if result == "destination_changed" else uploads.NOT_A_DIRECTORY
            uploads.finish_attempt(row["user_id"], row["upload_id"], token, "failed", error)
            return
    except Exception:
        # Never log an exception that might carry a presigned URL.
        logger.warning("[upload] transfer deferred upload={}", row["upload_id"])
    reset = uploads.finish_attempt(row["user_id"], row["upload_id"], token, "staged",
                                   "The transfer is waiting to retry.", now=get_unix_timestamp())
    if reset and reset["attempts"] < 5:
        uploads.enqueue(reset)


async def handle_upload_message(body):
    if body.get("Event") == "s3:TestEvent":
        return
    if "Records" in body:
        for record in body["Records"]:
            process_s3_event(record)
        return
    row = job_for_key(body.get("staging_key", ""))
    if row and body.get("upload_id") == row["upload_id"]:
        await transfer_upload(row)
