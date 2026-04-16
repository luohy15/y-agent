"""Link service."""

from typing import List, Optional
from storage.entity.dto import LinkActivity, LinkSummary
from storage.repository import link as link_repo


def add_link(
    user_id: int,
    url: str,
    title: Optional[str] = None,
    timestamp: Optional[int] = None,
) -> LinkActivity:
    return link_repo.save_link(user_id, url, title, timestamp or 0)


def add_links_batch(user_id: int, links: List[dict]) -> int:
    """Batch add links from dicts with url, title, timestamp. Returns count."""
    return link_repo.save_links_batch(user_id, links)


def get_link(user_id: int, activity_id: str) -> Optional[LinkActivity]:
    return link_repo.get_link(user_id, activity_id)


def list_links(
    user_id: int,
    start: Optional[int] = None,
    end: Optional[int] = None,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    link_ids: Optional[List[str]] = None,
    activity_ids: Optional[List[str]] = None,
    downloaded_only: bool = False,
) -> List[LinkActivity]:
    return link_repo.list_links(
        user_id, start=start, end=end, query=query,
        limit=limit, offset=offset, link_ids=link_ids,
        activity_ids=activity_ids, downloaded_only=downloaded_only,
    )


def list_link_summaries(
    user_id: int,
    start: Optional[int] = None,
    end: Optional[int] = None,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[LinkSummary]:
    return link_repo.list_link_summaries(
        user_id, start=start, end=end, query=query,
        limit=limit, offset=offset,
    )


def get_link_by_id(link_id: str):
    """Get a LinkEntity by link_id. Returns entity or None."""
    entities = link_repo.get_links_by_ids([link_id])
    return entities[0] if entities else None


def delete_link(user_id: int, activity_id: str) -> bool:
    return link_repo.delete_link(user_id, activity_id)


def request_downloads(urls: List[str]) -> List[dict]:
    """For each URL: upsert LinkEntity if needed, set download_status='pending'.
    Returns list of {link_id, base_url, url, download_status, is_activity_level}."""
    results = []
    for url in urls:
        info = link_repo.upsert_link_for_download(url)
        info['url'] = url
        results.append(info)
    return results


def update_download_status(link_id: str, status: str, content_key: Optional[str] = None, url: Optional[str] = None):
    """Update download status for a link. If url differs from base_url, update at activity level."""
    if url is not None:
        url = url.split('#')[0]  # strip fragment
        base_url = url.split('?')[0]
        if url != base_url:
            link_repo.update_link_activity_download_status(url, status, content_key=content_key)
            return
    link_repo.update_link_download_status(link_id, status, content_key=content_key)


def get_content_key_for_url(link_id: str, url: Optional[str] = None) -> Optional[str]:
    """Get content_key, checking activity-level first if url has query params."""
    if url:
        base_url = url.split('?')[0].split('#')[0]
        if url.split('#')[0] != base_url:
            key = link_repo.get_activity_content_key(url)
            if key:
                return key
    entity = get_link_by_id(link_id)
    if entity and entity.content_key:
        return entity.content_key
    return None


def get_content_key_by_activity_id(activity_id: str) -> Optional[str]:
    """Get content_key by activity_id. Checks activity-level first, then link-level."""
    return link_repo.get_content_key_by_activity_id(activity_id)


def update_link_title(link_id: str, title: str):
    """Update title for a link."""
    link_repo.update_link_title(link_id, title)


def send_download_task(user_id: int, link_id: str, url: str, activity_id: Optional[str] = None):
    """Enqueue a link download task via SQS or Celery."""
    import json
    import os
    payload = {
        "task_type": "link_download",
        "user_id": user_id,
        "link_id": link_id,
        "url": url,
    }
    if activity_id:
        payload["activity_id"] = activity_id

    queue_url = os.environ.get("SQS_QUEUE_URL")
    if queue_url:
        from storage.service.chat import _get_sqs_client
        client = _get_sqs_client()
        client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(payload),
        )
        return

    from storage.service.chat import _get_celery_app
    app = _get_celery_app()
    app.send_task("worker.tasks.process_link_download", kwargs=payload)
