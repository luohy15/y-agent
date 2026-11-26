"""S3 snapshots for shared note bodies.

One implementation for todo-share items and individual note shares. Keys are
built by ``storage.crypto.blob.share_note_object_key``; bodies are sealed with
the tenant envelope when encryption is active for the owner.
"""

import os
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import HTTPException

from storage.crypto.blob import open_body, seal_body

S3_BUCKET = os.environ.get("Y_AGENT_S3_BUCKET", "")


def _bucket() -> str:
    if not S3_BUCKET:
        raise HTTPException(status_code=500, detail="Y_AGENT_S3_BUCKET is not configured")
    return S3_BUCKET


def put_snapshot(key: str, body: bytes) -> None:
    boto3.client("s3").put_object(
        Bucket=_bucket(),
        Key=key,
        Body=seal_body(key, body),
        ContentType="text/markdown",
    )


def read_snapshot(key: Optional[str]) -> Optional[str]:
    """Return snapshot text. A missing object is None; other S3 errors are 503."""
    if not key:
        return None
    try:
        obj = boto3.client("s3").get_object(Bucket=_bucket(), Key=key)
        return open_body(key, obj["Body"].read()).decode("utf-8")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            return None
        raise HTTPException(status_code=503, detail="Note snapshot is temporarily unavailable") from exc


def delete_snapshot(key: Optional[str]) -> None:
    if not key or not S3_BUCKET:
        return
    try:
        boto3.client("s3").delete_object(Bucket=S3_BUCKET, Key=key)
    except ClientError:
        pass
