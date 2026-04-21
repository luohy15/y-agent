"""S3 upload helper shared by the batch link downloader."""

import os

import boto3


S3_BUCKET = os.environ.get("Y_AGENT_S3_BUCKET", "")


def s3_put(content_key: str, content: str) -> None:
    """Upload markdown content to s3://$Y_AGENT_S3_BUCKET/<content_key>."""
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=content_key,
        Body=content.encode("utf-8"),
        ContentType="text/markdown",
    )
