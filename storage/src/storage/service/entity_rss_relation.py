"""Entity-rss relation service."""

from typing import List
from storage.repository import entity_rss_relation as relation_repo


def create_relation(user_id: int, entity_id: str, rss_feed_id: str) -> bool:
    return relation_repo.create_relation(user_id, entity_id, rss_feed_id)


def delete_relation(user_id: int, entity_id: str, rss_feed_id: str) -> bool:
    return relation_repo.delete_relation(user_id, entity_id, rss_feed_id)


def list_by_entity(user_id: int, entity_id: str) -> List[str]:
    return relation_repo.list_by_entity(user_id, entity_id)


def list_by_feed(user_id: int, rss_feed_id: str) -> List[str]:
    return relation_repo.list_by_feed(user_id, rss_feed_id)
