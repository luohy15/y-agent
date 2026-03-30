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
) -> List[LinkActivity]:
    return link_repo.list_links(
        user_id, start=start, end=end, query=query,
        limit=limit, offset=offset,
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
    Returns list of {link_id, base_url, download_status}."""
    results = []
    for url in urls:
        entity = link_repo.upsert_link_for_download(url)
        results.append({
            'link_id': entity.link_id,
            'base_url': entity.base_url,
            'download_status': entity.download_status,
        })
    return results


def update_download_status(link_id: str, status: str, content_key: Optional[str] = None):
    """Update download status for a link."""
    link_repo.update_link_download_status(link_id, status, content_key=content_key)


def update_link_title(link_id: str, title: str):
    """Update title for a link."""
    link_repo.update_link_title(link_id, title)


def send_download_task(user_id: int, link_id: str, url: str):
    """Enqueue a link download task via SQS or Celery."""
    import json
    import os
    payload = {
        "task_type": "link_download",
        "user_id": user_id,
        "link_id": link_id,
        "url": url,
    }

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
