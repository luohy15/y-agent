"""Scheduled repair of notification, queue handoff and worker lease gaps."""

from loguru import logger
from storage.service import upload_job as uploads
from storage.util import get_unix_timestamp


def recover_authorized(client, row, now):
    paginator = client.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=uploads.bucket(), Prefix=row["staging_key"]):
        for version in page.get("Versions", []):
            if version["Key"] != row["staging_key"]:
                continue
            try:
                head = uploads.head_version(client, row, version["VersionId"])
            except Exception as exc:
                if uploads.is_absent(exc):
                    continue
                raise
            if uploads.valid_head(row, head):
                promoted = uploads.promote(row["user_id"], row["upload_id"], version["VersionId"], now)
                if promoted:
                    uploads.enqueue(promoted)
                return
    uploads.recover(row, now, uploads.DID_NOT_FINISH)


def handle_recover_upload_jobs():
    now = get_unix_timestamp()
    client = uploads.s3_client()
    count = 0
    for row in uploads.recovery_candidates(now):
        try:
            if row["status"] == "authorized":
                recover_authorized(client, row, now)
                continue
            try:
                uploads.head_version(client, row)
            except Exception as exc:
                if uploads.is_absent(exc):
                    uploads.recover(row, now, uploads.STAGED_EXPIRED)
                    continue
                raise
            if row["attempts"] >= 5:
                uploads.recover(row, now, uploads.ATTEMPTS_EXHAUSTED)
                continue
            recovered = uploads.recover(row, now)
            if recovered:
                uploads.enqueue(recovered)
                count += 1
        except Exception:
            logger.warning("[upload] recovery deferred upload={}", row["upload_id"])
    return {"status": "ok", "enqueued": count}
