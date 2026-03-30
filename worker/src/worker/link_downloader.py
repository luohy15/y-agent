"""Download link content via fetcher service, store to S3, update DB."""

import os

import boto3
import httpx

from storage.service import link as link_service

FETCHER_URL = os.environ.get("FETCHER_URL", "")
S3_BUCKET = os.environ.get("Y_AGENT_S3_BUCKET", "")


async def run_link_download(user_id: int, link_id: str, url: str):
    """Download link content via fetcher, store to S3, update DB."""
    link_service.update_download_status(link_id, "downloading")

    try:
        # Call fetcher service
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{FETCHER_URL}/fetch", json={"url": url})
            resp.raise_for_status()
            data = resp.json()
            content = data["content"]  # markdown string
            title = data.get("title", "")

        # Store to S3
        s3_key = f"links/{link_id}/content.md"
        s3 = boto3.client("s3")
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=content.encode("utf-8"),
            ContentType="text/markdown",
        )

        # Update DB: done + content_key
        link_service.update_download_status(link_id, "done", content_key=s3_key)

        # Update title if fetcher returned one
        if title:
            link_service.update_link_title(link_id, title)

    except Exception as e:
        link_service.update_download_status(link_id, "failed")
        raise
