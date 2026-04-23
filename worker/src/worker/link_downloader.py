"""S3 upload/download helpers shared by worker steps."""

import os
from typing import Optional, Union

import boto3
from botocore.exceptions import ClientError


S3_BUCKET = os.environ.get("Y_AGENT_S3_BUCKET", "")


def s3_put(content_key: str, content: Union[str, bytes], content_type: str = "text/markdown") -> None:
    """Upload content to s3://$Y_AGENT_S3_BUCKET/<content_key>."""
    body = content.encode("utf-8") if isinstance(content, str) else content
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=content_key,
        Body=body,
        ContentType=content_type,
    )


def s3_get(content_key: str) -> Optional[bytes]:
    """Download bytes from s3://$Y_AGENT_S3_BUCKET/<content_key>. Returns None if missing."""
    s3 = boto3.client("s3")
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=content_key)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404", "NotFound"):
            return None
        raise
    return resp["Body"].read()
