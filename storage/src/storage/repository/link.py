"""Function-based link repository using SQLAlchemy sessions."""

from collections import OrderedDict
from typing import List, Optional, Set
from storage.entity.link import LinkEntity, LinkActivityEntity
from storage.entity.dto import LinkActivity, LinkSummary
from storage.database.base import get_db
from storage.util import generate_id, generate_long_id


def _row_to_dto(activity: LinkActivityEntity, link: LinkEntity) -> LinkActivity:
    return LinkActivity(
        activity_id=activity.activity_id,
        link_id=link.id,
        url=activity.url,
        base_url=link.base_url,
        title=activity.title or link.title,
        timestamp=activity.timestamp,
        created_at=activity.created_at if activity.created_at else None,
        updated_at=activity.updated_at if activity.updated_at else None,
        created_at_unix=activity.created_at_unix if activity.created_at_unix else None,
        updated_at_unix=activity.updated_at_unix if activity.updated_at_unix else None,
    )


def list_links(
    user_id: int,
    start: Optional[int] = None,
    end: Optional[int] = None,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[LinkActivity]:
    with get_db() as session:
        q = (
            session.query(LinkActivityEntity, LinkEntity)
            .join(LinkEntity, LinkActivityEntity.link_id == LinkEntity.id)
            .filter(LinkActivityEntity.user_id == user_id)
        )
        if start is not None:
            q = q.filter(LinkActivityEntity.timestamp >= start)
        if end is not None:
            q = q.filter(LinkActivityEntity.timestamp <= end)
        if query:
            pattern = f"%{query}%"
            q = q.filter(
                (LinkEntity.title.like(pattern)) | (LinkEntity.base_url.like(pattern))
            )
        q = q.order_by(LinkActivityEntity.timestamp.desc())
        # Fetch extra rows to account for dedup filtering
        q = q.offset(offset)
        results: List[LinkActivity] = []
        # Track last-seen timestamp per base_url and per title; skip duplicates within 5 min
        last_ts_url: dict[str, int] = {}
        last_ts_title: dict[str, int] = {}
        window_ms = 5 * 60 * 1000
        for act, lnk in q.yield_per(200):
            title = act.title or lnk.title
            prev_url = last_ts_url.get(lnk.base_url)
            if prev_url is not None and prev_url - act.timestamp < window_ms:
                continue
            if title:
                prev_title = last_ts_title.get(title)
                if prev_title is not None and prev_title - act.timestamp < window_ms:
                    continue
                last_ts_title[title] = act.timestamp
            last_ts_url[lnk.base_url] = act.timestamp
            results.append(_row_to_dto(act, lnk))
            if len(results) >= limit:
                break
        return results


def list_link_summaries(
    user_id: int,
    start: Optional[int] = None,
    end: Optional[int] = None,
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[LinkSummary]:
    with get_db() as session:
        q = (
            session.query(LinkActivityEntity, LinkEntity)
            .join(LinkEntity, LinkActivityEntity.link_id == LinkEntity.id)
            .filter(LinkActivityEntity.user_id == user_id)
        )
        if start is not None:
            q = q.filter(LinkActivityEntity.timestamp >= start)
        if end is not None:
            q = q.filter(LinkActivityEntity.timestamp <= end)
        if query:
            pattern = f"%{query}%"
            q = q.filter(
                (LinkEntity.title.like(pattern)) | (LinkEntity.base_url.like(pattern))
            )
        q = q.order_by(LinkActivityEntity.timestamp.desc())
        q = q.offset(offset).limit(limit)

        # Group by link, preserving order of first appearance
        grouped: OrderedDict[int, LinkSummary] = OrderedDict()
        for act, lnk in q.all():
            if lnk.id not in grouped:
                grouped[lnk.id] = LinkSummary(
                    link_id=lnk.link_id,
                    base_url=lnk.base_url,
                    title=lnk.title,
                    timestamps=[act.timestamp],
                )
            else:
                grouped[lnk.id].timestamps.append(act.timestamp)
        return list(grouped.values())


def get_link(user_id: int, activity_id: str) -> Optional[LinkActivity]:
    with get_db() as session:
        row = (
            session.query(LinkActivityEntity, LinkEntity)
            .join(LinkEntity, LinkActivityEntity.link_id == LinkEntity.id)
            .filter(LinkActivityEntity.user_id == user_id, LinkActivityEntity.activity_id == activity_id)
            .first()
        )
        if not row:
            return None
        return _row_to_dto(row[0], row[1])


def _strip_query(url: str) -> str:
    """Return URL without query string and fragment."""
    idx = url.find('?')
    if idx != -1:
        return url[:idx]
    idx = url.find('#')
    if idx != -1:
        return url[:idx]
    return url


def _upsert_link(session, url: str, title: Optional[str]) -> LinkEntity:
    """Upsert a link by base_url (via url_hash). Updates url/title to latest."""
    base_url = _strip_query(url)
    entity = session.query(LinkEntity).filter_by(base_url=base_url).first()
    if entity:
        if title is not None:
            entity.title = title
    else:
        link_id = generate_id()
        while session.query(LinkEntity).filter_by(link_id=link_id).first():
            link_id = generate_id()
        entity = LinkEntity(link_id=link_id, base_url=base_url, title=title)
        session.add(entity)
        session.flush()
    return entity


def save_link(user_id: int, url: str, title: Optional[str], timestamp: int) -> LinkActivity:
    with get_db() as session:
        link = _upsert_link(session, url, title)
        # Dedup: skip if same user+timestamp already exists
        existing = session.query(LinkActivityEntity).filter_by(
            user_id=user_id, timestamp=timestamp,
        ).first()
        if existing:
            return _row_to_dto(existing, link)
        activity = LinkActivityEntity(
            user_id=user_id,
            activity_id=generate_long_id(),
            link_id=link.id,
            url=url,
            title=title,
            timestamp=timestamp,
        )
        session.add(activity)
        session.flush()
        return _row_to_dto(activity, link)


def _batch_generate_long_ids(n: int, existing: Set[str] = set()) -> List[str]:
    """Pre-generate n unique long IDs, avoiding collisions with existing set."""
    ids: List[str] = []
    seen = set(existing)
    while len(ids) < n:
        new_id = generate_long_id()
        if new_id not in seen:
            seen.add(new_id)
            ids.append(new_id)
    return ids


def save_links_batch(user_id: int, links: List[dict]) -> int:
    """Batch upsert links and insert activities. Returns count of activities created."""
    count = 0
    activity_ids = _batch_generate_long_ids(len(links))
    with get_db() as session:
        for i, item in enumerate(links):
            link = _upsert_link(session, item['url'], item.get('title'))
            # Dedup: skip if same user+timestamp already exists
            existing = session.query(LinkActivityEntity).filter_by(
                user_id=user_id, timestamp=item['timestamp'],
            ).first()
            if existing:
                continue
            activity = LinkActivityEntity(
                user_id=user_id,
                activity_id=activity_ids[i],
                link_id=link.id,
                url=item['url'],
                title=item.get('title'),
                timestamp=item['timestamp'],
            )
            session.add(activity)
            count += 1
    return count


def delete_link(user_id: int, activity_id: str) -> bool:
    with get_db() as session:
        entity = session.query(LinkActivityEntity).filter_by(
            user_id=user_id, activity_id=activity_id
        ).first()
        if not entity:
            return False
        session.delete(entity)
        return True
