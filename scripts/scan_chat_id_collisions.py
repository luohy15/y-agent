#!/usr/bin/env python3
"""Report chat rows whose blob create_time is > 1h after the row created_at.

A silent overwrite (pre-3131 upsert-on-create) leaves the row's created_at at the
original insert time while rewriting json_content with a later Chat.create_time.
This scan surfaces those victims for maintainer review.

Usage (from a checkout with DATABASE_URL / DATABASE_URL_DEV set):

    uv run python scripts/scan_chat_id_collisions.py
    uv run python scripts/scan_chat_id_collisions.py --threshold-hours 1
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from storage.database.base import get_db
from storage.entity.chat import ChatEntity


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def scan(threshold_hours: float = 1.0) -> list[dict]:
    threshold = timedelta(hours=threshold_hours)
    victims: list[dict] = []
    with get_db() as session:
        rows = session.query(
            ChatEntity.chat_id,
            ChatEntity.user_id,
            ChatEntity.created_at,
            ChatEntity.topic,
            ChatEntity.skill,
            ChatEntity.trace_id,
            ChatEntity.json_content,
        ).all()
        for row in rows:
            try:
                blob = json.loads(row.json_content or "{}")
            except (TypeError, ValueError):
                continue
            blob_create = _parse_iso(blob.get("create_time") or blob.get("createTime"))
            row_create = _parse_iso(row.created_at)
            if blob_create is None or row_create is None:
                continue
            delta = blob_create - row_create
            if delta > threshold:
                victims.append({
                    "chat_id": row.chat_id,
                    "user_id": row.user_id,
                    "row_created_at": row.created_at,
                    "blob_create_time": blob.get("create_time") or blob.get("createTime"),
                    "delta_hours": round(delta.total_seconds() / 3600, 2),
                    "topic": row.topic or "",
                    "skill": row.skill or "",
                    "trace_id": row.trace_id or "",
                })
    victims.sort(key=lambda v: (v["user_id"], v["chat_id"]))
    return victims


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threshold-hours",
        type=float,
        default=1.0,
        help="blob create_time must exceed row created_at by more than this many hours",
    )
    args = parser.parse_args(argv)
    victims = scan(threshold_hours=args.threshold_hours)
    if not victims:
        print("no collision victims found")
        return 0
    print(f"found {len(victims)} candidate overwrite(s):")
    for v in victims:
        print(
            f"  chat_id={v['chat_id']} user_id={v['user_id']} "
            f"row_created_at={v['row_created_at']} blob_create_time={v['blob_create_time']} "
            f"delta_hours={v['delta_hours']} topic={v['topic']!r} skill={v['skill']!r} "
            f"trace_id={v['trace_id']!r}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
