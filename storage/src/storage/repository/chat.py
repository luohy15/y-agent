"""Chat repository using SQLAlchemy ORM."""

import json
from typing import Dict, List, Optional
from dataclasses import dataclass

from sqlalchemy import or_
from sqlalchemy.orm import defer

from storage.entity.chat import ChatEntity
from storage.entity.user import UserEntity  # noqa: F401 - needed for ChatEntity FK resolution
from storage.entity.dto import Chat
from storage.database.base import get_db


@dataclass
class ChatSummary:
    chat_id: str
    title: str
    created_at: str
    updated_at: str
    skill: str = ""
    created_at_unix: int = 0
    updated_at_unix: int = 0


def _entity_to_chat(entity: ChatEntity) -> Chat:
    return Chat.from_dict(json.loads(entity.json_content))


async def list_chats(user_id: int, limit: int = 10, query: Optional[str] = None, offset: int = 0, trace_id: Optional[str] = None) -> List[ChatSummary]:
    with get_db() as session:
        q = (session.query(ChatEntity)
             .filter_by(user_id=user_id)
             .options(defer(ChatEntity.json_content)))
        if query:
            q = q.filter(or_(
                ChatEntity.title.ilike(f"%{query}%"),
                ChatEntity.search_text.ilike(f"%{query}%"),
            ))
        if trace_id:
            # Filter by trace_id in Python since JSON array contains is DB-specific
            q = q.filter(ChatEntity.trace_ids.isnot(None))
            rows = (q.order_by(ChatEntity.updated_at.desc()).all())
            filtered = [
                row for row in rows
                if isinstance(row.trace_ids, list) and trace_id in row.trace_ids
            ]
            return [
                ChatSummary(
                    chat_id=row.chat_id,
                    title=row.title or "",
                    created_at=row.created_at or "",
                    updated_at=row.updated_at or "",
                )
                for row in filtered[offset:offset + limit]
            ]
        rows = (q.order_by(ChatEntity.updated_at.desc())
                 .offset(offset)
                 .limit(limit)
                 .all())
        return [
            ChatSummary(
                chat_id=row.chat_id,
                title=row.title or "",
                created_at=row.created_at or "",
                updated_at=row.updated_at or "",
            )
            for row in rows
        ]


async def get_chat(user_id: int, chat_id: str) -> Optional[Chat]:
    with get_db() as session:
        row = session.query(ChatEntity).filter_by(user_id=user_id, chat_id=chat_id).first()
        if not row:
            return None
        try:
            return _entity_to_chat(row)
        except Exception as e:
            print(f"Error parsing chat JSON: {e}")
            return None


async def add_chat(user_id: int, chat: Chat) -> Chat:
    return await save_chat(user_id, chat)


async def update_chat(user_id: int, chat: Chat) -> Chat:
    existing = await get_chat(user_id, chat.id)
    if not existing:
        raise ValueError(f"Chat with id {chat.id} not found")
    return await save_chat(user_id, chat)


async def delete_chat(user_id: int, chat_id: str) -> bool:
    with get_db() as session:
        count = session.query(ChatEntity).filter_by(user_id=user_id, chat_id=chat_id).delete()
        return count > 0


def _extract_content_text(content) -> str:
    """Extract plain text from message content (str or list of ContentPart)."""
    if isinstance(content, str):
        return content
    if content:
        return " ".join(part.text for part in content if hasattr(part, 'text') and part.text)
    return ""


def _extract_title(chat: Chat) -> str:
    for m in chat.messages:
        if m.role == 'user':
            text = _extract_content_text(m.content)
            return text[:100] if text else ""
    # Fallback to first assistant message if no user message found
    for m in chat.messages:
        if m.role == 'assistant':
            text = _extract_content_text(m.content).strip()
            if text:
                return text[:100]
    return ""


def _extract_search_text(chat: Chat) -> str:
    """Extract searchable text from chat messages (user + assistant text only)."""
    parts = []
    for m in chat.messages:
        if m.role in ('user', 'assistant'):
            text = _extract_content_text(m.content).strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


def _save_chat_sync(user_id: int, chat: Chat) -> Chat:
    from storage.util import get_utc_iso8601_timestamp
    chat.update_time = get_utc_iso8601_timestamp()

    with get_db() as session:
        entity = session.query(ChatEntity).filter_by(user_id=user_id, chat_id=chat.id).first()
        content = json.dumps(chat.to_dict())
        title = _extract_title(chat)
        search_text = _extract_search_text(chat)
        if entity:
            entity.json_content = content
            entity.title = title
            entity.search_text = search_text
            entity.origin_chat_id = chat.origin_chat_id
            entity.external_id = chat.external_id
            entity.backend = chat.backend
            entity.channel_id = chat.channel_id
            entity.skill = chat.skill
            entity.active_trace_id = chat.active_trace_id
            entity.trace_ids = chat.trace_ids
        else:
            entity = ChatEntity(
                user_id=user_id,
                chat_id=chat.id,
                title=title,
                external_id=chat.external_id,
                backend=chat.backend,
                origin_chat_id=chat.origin_chat_id,
                channel_id=chat.channel_id,
                skill=chat.skill,
                active_trace_id=chat.active_trace_id,
                trace_ids=chat.trace_ids,
                json_content=content,
                search_text=search_text,
            )
            session.add(entity)
        return chat


async def save_chat(user_id: int, chat: Chat) -> Chat:
    return _save_chat_sync(user_id, chat)


def _get_chat_by_id_sync(chat_id: str) -> Optional[Chat]:
    """Fetch chat by ID without user_id filter (for worker use). Sync."""
    with get_db() as session:
        row = session.query(ChatEntity).filter_by(chat_id=chat_id).first()
        if not row:
            return None
        try:
            return _entity_to_chat(row)
        except Exception as e:
            print(f"Error parsing chat JSON: {e}")
            return None


def _save_chat_by_id_sync(chat: Chat) -> Chat:
    """Save chat without user_id filter (for worker use). Sync."""
    from storage.util import get_utc_iso8601_timestamp
    chat.update_time = get_utc_iso8601_timestamp()

    with get_db() as session:
        entity = session.query(ChatEntity).filter_by(chat_id=chat.id).first()
        content = json.dumps(chat.to_dict())
        title = _extract_title(chat)
        search_text = _extract_search_text(chat)
        if entity:
            entity.json_content = content
            entity.title = title
            entity.search_text = search_text
            entity.origin_chat_id = chat.origin_chat_id
            entity.external_id = chat.external_id
            entity.backend = chat.backend
            entity.channel_id = chat.channel_id
            entity.skill = chat.skill
            entity.active_trace_id = chat.active_trace_id
            entity.trace_ids = chat.trace_ids
        else:
            raise ValueError(f"Chat with id {chat.id} not found")
        return chat


async def get_chat_by_id(chat_id: str) -> Optional[Chat]:
    return _get_chat_by_id_sync(chat_id)


def find_external_id_map(user_id: int, backend: str) -> Dict[str, tuple]:
    """Return {external_id: (chat_id, updated_at_unix)} for all chats with the given backend."""
    with get_db() as session:
        rows = (session.query(ChatEntity.external_id, ChatEntity.chat_id, ChatEntity.updated_at_unix)
                .filter_by(user_id=user_id, backend=backend)
                .filter(ChatEntity.external_id.isnot(None))
                .all())
        return {r.external_id: (r.chat_id, r.updated_at_unix) for r in rows}


async def find_chat_by_origin(user_id: int, origin_chat_id: str) -> List[Chat]:
    """Find chats by origin_chat_id column (for share dedup)."""
    with get_db() as session:
        rows = (session.query(ChatEntity)
                .filter_by(user_id=user_id, origin_chat_id=origin_chat_id)
                .all())
        result = []
        for row in rows:
            try:
                result.append(_entity_to_chat(row))
            except Exception:
                pass
        return result


async def save_chat_by_id(chat: Chat) -> Chat:
    return _save_chat_by_id_sync(chat)


def update_channel_id(user_id: int, chat_id: str, channel_id: str) -> None:
    """Update the channel_id for a chat, clearing it from any other chat that had it."""
    with get_db() as session:
        # Clear channel_id from any other chat that currently owns it
        old_entities = session.query(ChatEntity).filter_by(user_id=user_id, channel_id=channel_id).filter(
            ChatEntity.chat_id != chat_id
        ).all()
        for entity in old_entities:
            entity.channel_id = None
            data = json.loads(entity.json_content)
            data.pop("channel_id", None)
            entity.json_content = json.dumps(data)
        # Set channel_id on the target chat (both column and json_content)
        entity = session.query(ChatEntity).filter_by(user_id=user_id, chat_id=chat_id).first()
        if entity:
            entity.channel_id = channel_id
            data = json.loads(entity.json_content)
            data["channel_id"] = channel_id
            entity.json_content = json.dumps(data)


def list_trace_ids(user_id: int, limit: int = 50, offset: int = 0, trace_id: str = None) -> list:
    """List distinct trace_ids from all chats' trace_ids lists, ordered by most recently updated."""
    with get_db() as session:
        rows = (session.query(ChatEntity.trace_ids, ChatEntity.updated_at, ChatEntity.updated_at_unix)
                .filter_by(user_id=user_id)
                .filter(ChatEntity.trace_ids.isnot(None))
                .order_by(ChatEntity.updated_at_unix.desc())
                .all())
        # Collect all trace_ids, keeping the most recent updated_at for each
        trace_map: dict = {}  # trace_id -> (updated_at, updated_at_unix)
        for row in rows:
            if not isinstance(row.trace_ids, list):
                continue
            for tid in row.trace_ids:
                if tid not in trace_map or (row.updated_at_unix or 0) > trace_map[tid][1]:
                    trace_map[tid] = (row.updated_at or "", row.updated_at_unix or 0)
        # Filter by trace_id if provided
        if trace_id:
            trace_map = {tid: info for tid, info in trace_map.items() if trace_id in tid}
        # Sort by most recent
        sorted_traces = sorted(trace_map.items(), key=lambda x: x[1][1], reverse=True)
        return [
            {"trace_id": tid, "updated_at": info[0]}
            for tid, info in sorted_traces[offset:offset + limit]
        ]


def find_chat_by_skill_and_trace(user_id: int, skill: str, trace_id: str) -> Optional[Chat]:
    """Find a chat with the given skill whose active trace matches trace_id."""
    with get_db() as session:
        row = (session.query(ChatEntity)
               .filter_by(user_id=user_id, skill=skill, active_trace_id=trace_id)
               .order_by(ChatEntity.updated_at_unix.desc())
               .first())
        if row:
            try:
                return _entity_to_chat(row)
            except Exception:
                pass
        return None


def find_chats_with_messages_by_trace_id(user_id: int, trace_id: str) -> list:
    """Find all chats in a trace, returning (chat_id, title, skill, json_content) tuples.
    Includes json_content so caller can extract message-level time segments."""
    with get_db() as session:
        rows = (session.query(ChatEntity)
                .filter_by(user_id=user_id)
                .filter(ChatEntity.trace_ids.isnot(None))
                .order_by(ChatEntity.created_at_unix.asc())
                .all())
        return [
            (row.chat_id, row.title or "", row.skill or "", row.json_content)
            for row in rows
            if isinstance(row.trace_ids, list) and trace_id in row.trace_ids
        ]


def find_chats_by_trace_id(user_id: int, trace_id: str) -> List[ChatSummary]:
    """Find all chats that participate in a given trace."""
    from sqlalchemy import cast, String
    with get_db() as session:
        rows = (session.query(ChatEntity)
                .filter_by(user_id=user_id)
                .filter(ChatEntity.trace_ids.isnot(None))
                .options(defer(ChatEntity.json_content))
                .order_by(ChatEntity.updated_at_unix.desc())
                .all())
        # Filter in Python since JSON array contains is DB-specific
        return [
            ChatSummary(
                chat_id=row.chat_id,
                title=row.title or "",
                created_at=row.created_at or "",
                updated_at=row.updated_at or "",
                skill=row.skill or "",
                created_at_unix=row.created_at_unix or 0,
                updated_at_unix=row.updated_at_unix or 0,
            )
            for row in rows
            if isinstance(row.trace_ids, list) and trace_id in row.trace_ids
        ]


def find_chat_by_channel_sync(user_id: int, channel_id: str) -> Optional[Chat]:
    """Find the most recent chat for a given channel_id (e.g. 'telegram:123')."""
    with get_db() as session:
        row = (session.query(ChatEntity)
               .filter_by(user_id=user_id, channel_id=channel_id)
               .order_by(ChatEntity.updated_at_unix.desc())
               .first())
        if not row:
            return None
        try:
            return _entity_to_chat(row)
        except Exception as e:
            print(f"Error parsing chat JSON: {e}")
            return None


