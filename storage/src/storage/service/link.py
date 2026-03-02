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


def delete_link(user_id: int, activity_id: str) -> bool:
    return link_repo.delete_link(user_id, activity_id)
