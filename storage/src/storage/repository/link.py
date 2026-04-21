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
        link_id=link.link_id,
        url=activity.url,
        base_url=link.base_url,
        title=activity.title or link.title,
        timestamp=activity.timestamp,
        created_at=activity.created_at if activity.created_at else None,
        updated_at=activity.updated_at if activity.updated_at else None,
        created_at_unix=activity.created_at_unix if activity.created_at_unix else None,
        updated_at_unix=activity.updated_at_unix if activity.updated_at_unix else None,
        download_status=activity.download_status or link.download_status,
        content_key=activity.content_key or link.content_key,
        source=link.source,
        source_feed_id=link.source_feed_id,
    )


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
    with get_db() as session:
        q = (
            session.query(LinkActivityEntity, LinkEntity)
            .join(LinkEntity, LinkActivityEntity.link_id == LinkEntity.id)
            .filter(LinkActivityEntity.user_id == user_id)
        )
        if downloaded_only:
            q = q.filter(LinkEntity.download_status == "done")
        if link_ids is not None:
            q = q.filter(LinkEntity.link_id.in_(link_ids))
        if activity_ids is not None:
            q = q.filter(LinkActivityEntity.activity_id.in_(activity_ids))
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
                    download_status=lnk.download_status,
                    content_key=lnk.content_key,
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
    if not links:
        return 0

    with get_db() as session:
        # 1. Collect all base_urls and timestamps
        base_url_map: dict[str, dict] = {}  # base_url -> latest item (for title update)
        for item in links:
            base_url = _strip_query(item['url'])
            # Keep latest title per base_url
            existing = base_url_map.get(base_url)
            if existing is None or item['timestamp'] > existing['timestamp']:
                base_url_map[base_url] = item
            item['_base_url'] = base_url

        timestamps = [item['timestamp'] for item in links]

        # 2. Batch load existing links by base_url
        existing_links = session.query(LinkEntity).filter(
            LinkEntity.base_url.in_(list(base_url_map.keys()))
        ).all()
        link_by_base_url: dict[str, LinkEntity] = {l.base_url: l for l in existing_links}

        # 3. Batch load existing activities by user+timestamp for dedup
        existing_activities = session.query(LinkActivityEntity.timestamp).filter(
            LinkActivityEntity.user_id == user_id,
            LinkActivityEntity.timestamp.in_(timestamps),
        ).all()
        existing_ts: Set[int] = {row.timestamp for row in existing_activities}

        # 4. Upsert links (only new ones need insert, existing get title updated)
        for base_url, item in base_url_map.items():
            entity = link_by_base_url.get(base_url)
            if entity:
                title = item.get('title')
                if title is not None:
                    entity.title = title
            else:
                link_id = generate_id()
                entity = LinkEntity(link_id=link_id, base_url=base_url, title=item.get('title'))
                session.add(entity)
                link_by_base_url[base_url] = entity
        session.flush()  # get IDs for new links

        # 5. Bulk insert new activities (dedup within batch by timestamp too)
        count = 0
        seen_ts: Set[int] = set()
        new_items: List[dict] = []
        for item in links:
            if item['timestamp'] not in existing_ts and item['timestamp'] not in seen_ts:
                seen_ts.add(item['timestamp'])
                new_items.append(item)
        activity_ids = _batch_generate_long_ids(len(new_items))
        for i, item in enumerate(new_items):
            link_entity = link_by_base_url[item['_base_url']]
            activity = LinkActivityEntity(
                user_id=user_id,
                activity_id=activity_ids[i],
                link_id=link_entity.id,
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


def get_links_by_ids(link_ids: List[str]) -> List[LinkEntity]:
    """Fetch LinkEntity rows by link_id list."""
    if not link_ids:
        return []
    with get_db() as session:
        return session.query(LinkEntity).filter(LinkEntity.link_id.in_(link_ids)).all()


def get_links_with_latest_activity(user_id: int, link_ids: List[str]) -> List[dict]:
    """Fetch links with their latest activity_id for a given user."""
    if not link_ids:
        return []
    from sqlalchemy import func
    with get_db() as session:
        links = session.query(LinkEntity).filter(LinkEntity.link_id.in_(link_ids)).all()
        link_id_to_entity = {l.link_id: l for l in links}
        # Get latest activity_id per link (by internal id)
        link_internal_ids = [l.id for l in links]
        activity_rows = (
            session.query(
                LinkActivityEntity.link_id,
                func.max(LinkActivityEntity.activity_id).label("activity_id"),
            )
            .filter(
                LinkActivityEntity.user_id == user_id,
                LinkActivityEntity.link_id.in_(link_internal_ids),
            )
            .group_by(LinkActivityEntity.link_id)
            .all()
        )
        internal_to_activity = {r.link_id: r.activity_id for r in activity_rows}
        result = []
        for link_id_str in link_ids:
            entity = link_id_to_entity.get(link_id_str)
            if not entity:
                continue
            result.append({
                "link_id": entity.link_id,
                "base_url": entity.base_url,
                "title": entity.title,
                "download_status": entity.download_status,
                "activity_id": internal_to_activity.get(entity.id),
            })
        return result


def get_links_by_urls(urls: List[str]) -> List[LinkEntity]:
    """Fetch LinkEntity rows by base_url (strips query params first)."""
    if not urls:
        return []
    base_urls = [_strip_query(u) for u in urls]
    with get_db() as session:
        return session.query(LinkEntity).filter(LinkEntity.base_url.in_(base_urls)).all()


def update_link_download_status(link_id: str, status: str, content_key: Optional[str] = None):
    """Update download_status and optionally content_key for a link."""
    with get_db() as session:
        entity = session.query(LinkEntity).filter_by(link_id=link_id).first()
        if not entity:
            return
        entity.download_status = status
        if content_key is not None:
            entity.content_key = content_key


def update_link_title(link_id: str, title: str):
    """Update title for a link."""
    with get_db() as session:
        entity = session.query(LinkEntity).filter_by(link_id=link_id).first()
        if entity:
            entity.title = title


def upsert_link_for_download(url: str) -> dict:
    """Upsert a link by base_url. Set download_status to pending at link or activity level.
    Returns dict with link_id, base_url, download_status, is_activity_level, activity_id."""
    url = url.split('#')[0]  # strip fragment
    base_url = _strip_query(url)
    is_activity_level = (url != base_url)
    with get_db() as session:
        entity = session.query(LinkEntity).filter_by(base_url=base_url).first()
        if not entity:
            link_id = generate_id()
            while session.query(LinkEntity).filter_by(link_id=link_id).first():
                link_id = generate_id()
            entity = LinkEntity(link_id=link_id, base_url=base_url)
            session.add(entity)
            session.flush()
        activity_id = None
        if is_activity_level:
            # Set pending on all activities matching this URL, pick first activity_id
            activities = session.query(LinkActivityEntity).filter_by(url=url).all()
            for act in activities:
                act.download_status = 'pending'
                if activity_id is None:
                    activity_id = act.activity_id
        else:
            entity.download_status = 'pending'
        return {
            'link_id': entity.link_id,
            'base_url': entity.base_url,
            'download_status': 'pending',
            'is_activity_level': is_activity_level,
            'activity_id': activity_id,
        }


def update_link_activity_download_status(url: str, status: str, content_key: Optional[str] = None):
    """Update download_status on all activities matching this exact URL."""
    with get_db() as session:
        activities = session.query(LinkActivityEntity).filter_by(url=url).all()
        for act in activities:
            act.download_status = status
            if content_key is not None:
                act.content_key = content_key


def get_activity_content_key(url: str) -> Optional[str]:
    """Get content_key from an activity matching this exact URL."""
    with get_db() as session:
        act = session.query(LinkActivityEntity).filter_by(url=url).first()
        if act and act.content_key:
            return act.content_key
        return None


def set_link_source_if_null(link_id: str, source: str, source_feed_id: Optional[str]):
    """Set source/source_feed_id on a LinkEntity only when source is currently null."""
    with get_db() as session:
        entity = session.query(LinkEntity).filter_by(link_id=link_id).first()
        if not entity:
            return
        if entity.source is None:
            entity.source = source
            entity.source_feed_id = source_feed_id


def list_pending_rss_links(limit: int) -> List[dict]:
    """Return links with source='rss' and download_status IS NULL, joined to rss_feed
    to resolve the owning user_id. Orphan links (feed deleted) are skipped."""
    from storage.entity.rss_feed import RssFeedEntity
    with get_db() as session:
        rows = (
            session.query(LinkEntity, RssFeedEntity.user_id)
            .join(RssFeedEntity, RssFeedEntity.rss_feed_id == LinkEntity.source_feed_id)
            .filter(LinkEntity.source == 'rss', LinkEntity.download_status.is_(None))
            .order_by(LinkEntity.id.asc())
            .limit(limit)
            .all()
        )
        return [
            {
                'link_id': lnk.link_id,
                'base_url': lnk.base_url,
                'source_feed_id': lnk.source_feed_id,
                'user_id': user_id,
            }
            for lnk, user_id in rows
        ]


def get_content_key_by_activity_id(activity_id: str) -> Optional[str]:
    """Get content_key for a given activity_id.
    Checks activity-level content_key first, then falls back to link-level."""
    with get_db() as session:
        row = (
            session.query(LinkActivityEntity, LinkEntity)
            .join(LinkEntity, LinkActivityEntity.link_id == LinkEntity.id)
            .filter(LinkActivityEntity.activity_id == activity_id)
            .first()
        )
        if not row:
            return None
        act, link = row
        # Activity-level content takes priority
        if act.content_key:
            return act.content_key
        # Fall back to link-level content
        if link.content_key:
            return link.content_key
        return None
