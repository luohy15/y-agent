"""Chat repository using SQLAlchemy ORM."""

import json
from typing import Dict, List, Optional
from dataclasses import dataclass

from loguru import logger
from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from storage.entity.chat import ChatEntity
from storage.entity.user import UserEntity  # noqa: F401 - needed for ChatEntity FK resolution
from storage.entity.dto import Chat
from storage.database.base import get_db
from storage.util import apply_time_filter


class ChatIdCollision(Exception):
    """Raised when creating a chat would overwrite an existing (user_id, chat_id)."""

    def __init__(self, user_id: int, chat_id: str):
        self.user_id = user_id
        self.chat_id = chat_id
        super().__init__(f"chat_id {chat_id!r} already exists for user_id={user_id}")


@dataclass
class ChatSummary:
    chat_id: str
    title: str
    created_at: str
    updated_at: str
    topic: str = ""
    skill: str = ""
    trace_id: str = ""
    routine_id: str = ""
    routine_name: str = ""
    backend: str = ""
    bot_name: str = ""
    tier: str = ""
    created_at_unix: int = 0
    updated_at_unix: int = 0
    status: str = "idle"
    unread: bool = False
    needs_attention: bool = False


def _entity_to_chat(entity: ChatEntity) -> Chat:
    """Hydrate the Chat DTO from `json_content`, then apply the promoted columns.

    Fields promoted to real columns exist twice: once inside the `json_content`
    blob (written by `Chat.to_dict`) and once as a column. The column is always
    the write target (`_save_chat_*_sync`), so it is the side that SQL can
    reach — which means a promoted field MUST be re-read here or a manual
    migration that rewrites the column silently does nothing at runtime.

    `external_id` is read **unconditionally**: NULL is a meaningful value
    ("this chat has no resumable backend session"), so it cannot fall back to
    the blob's stale copy the way the metadata fields below do. That fallback
    is exactly what made migration 2930_drop_non_claude_code_backends.sql
    ineffective: it NULLed the column on the 999 chats it repointed, the blob
    kept the foreign codex/grok session id on the 983 of them that had one, and
    every one of those relaunched `claude -p -r <foreign-uuid>` and died.
    """
    chat = Chat.from_dict(json.loads(entity.json_content))
    # Unconditional: NULL means "no resumable session", not "not promoted yet".
    chat.external_id = entity.external_id or None
    if entity.trace_id is not None:
        chat.trace_id = entity.trace_id
    if entity.backend is not None:
        chat.backend = entity.backend
    if entity.bot_name is not None:
        chat.bot_name = entity.bot_name
    if entity.tier is not None:
        chat.tier = entity.tier
    if entity.skill is not None:
        chat.skill = entity.skill
    if entity.routine_id is not None:
        chat.routine_id = entity.routine_id
    return chat


async def list_chats(
    user_id: int,
    limit: int = 10,
    query: Optional[str] = None,
    offset: int = 0,
    trace_id: Optional[str] = None,
    topic: Optional[str] = None,
    skill: Optional[str] = None,
    tier: Optional[str] = None,
    bot_name: Optional[str] = None,
    status: Optional[str] = None,
    routine_id: Optional[str] = None,
    routine_name: Optional[str] = None,
    routine_only: Optional[bool] = None,
    tag: Optional[str] = None,
    on: Optional[str] = None,
    from_: Optional[str] = None,
    to: Optional[str] = None,
    created_on: Optional[str] = None,
    created_from: Optional[str] = None,
    created_to: Optional[str] = None,
    updated_on: Optional[str] = None,
    updated_from: Optional[str] = None,
    updated_to: Optional[str] = None,
) -> List[ChatSummary]:
    with get_db() as session:
        q = (session.query(ChatEntity)
             .filter_by(user_id=user_id)
             .options(defer(ChatEntity.json_content)))
        if query:
            q = q.filter(or_(
                ChatEntity.title.ilike(f"%{query}%"),
                ChatEntity.search_text.ilike(f"%{query}%"),
            ))
        if tag:
            from storage.entity.entity_tag import EntityTagEntity
            q = q.filter(ChatEntity.chat_id.in_(
                session.query(EntityTagEntity.entity_id).filter_by(
                    user_id=user_id, entity_type="chat", tag=tag
                )
            ))
        if trace_id:
            q = q.filter(ChatEntity.trace_id == trace_id)
        if topic:
            q = q.filter(ChatEntity.topic == topic)
        if skill:
            q = q.filter(ChatEntity.skill == skill)
        if tier:
            q = q.filter(ChatEntity.tier == tier)
        if bot_name:
            q = q.filter(ChatEntity.bot_name == bot_name)
        # Routine name<->id is resolved here: chats only store routine_id, but the UI
        # filters/displays by the friendlier routine name. Build a per-user id->name
        # map once, used both to filter (name -> ids) and to annotate each row.
        from storage.entity.routine import RoutineEntity
        routine_name_by_id = {
            r_id: r_name
            for r_id, r_name in session.query(RoutineEntity.routine_id, RoutineEntity.name)
            .filter_by(user_id=user_id).all()
        }
        if routine_id:
            q = q.filter(ChatEntity.routine_id == routine_id)
        if routine_name:
            matching_ids = [rid for rid, rname in routine_name_by_id.items() if rname == routine_name]
            q = q.filter(ChatEntity.routine_id.in_(matching_ids or [""]))
        if routine_only:
            q = q.filter(ChatEntity.routine_id.isnot(None), ChatEntity.routine_id != "")
        if status:
            q = q.filter(ChatEntity.status == status)
        q = apply_time_filter(q, ChatEntity.updated_at, on=on, from_=from_, to=to)
        q = apply_time_filter(q, ChatEntity.created_at, on=created_on, from_=created_from, to=created_to)
        q = apply_time_filter(q, ChatEntity.updated_at, on=updated_on, from_=updated_from, to=updated_to)
        # Attention precedence before recency: needs_attention rows first, then
        # unread, then neutral rows, each bucket ordered by recency. A row
        # outside the fetched page can never be promoted by a client-side sort,
        # so this has to happen before offset/limit.
        rows = (q.order_by(
                    ChatEntity.needs_attention.desc(),
                    ChatEntity.unread.desc(),
                    ChatEntity.updated_at_unix.desc(),
                )
                 .offset(offset)
                 .limit(limit)
                 .all())
        return [
            ChatSummary(
                chat_id=row.chat_id,
                title=row.title or "",
                created_at=row.created_at or "",
                updated_at=row.updated_at or "",
                topic=row.topic or "",
                skill=row.skill or "",
                trace_id=row.trace_id or "",
                routine_id=row.routine_id or "",
                routine_name=routine_name_by_id.get(row.routine_id or "", ""),
                backend=row.backend or "",
                bot_name=row.bot_name or "",
                tier=row.tier or "",
                status=row.status or "idle",
                unread=bool(row.unread),
                needs_attention=bool(row.needs_attention),
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
            logger.exception("Error parsing chat JSON: {}", e)
            return None


def chat_id_exists(user_id: int, chat_id: str) -> bool:
    """Return True if (user_id, chat_id) already has a row."""
    with get_db() as session:
        return (
            session.query(ChatEntity.id)
            .filter_by(user_id=user_id, chat_id=chat_id)
            .first()
            is not None
        )


def _chat_status(chat: Chat) -> str:
    if chat.running:
        return "running"
    if chat.interrupted:
        return "interrupted"
    return "idle"


def _insert_chat_sync(user_id: int, chat: Chat) -> Chat:
    """Insert a new chat row. Never updates an existing row.

    Raises ChatIdCollision on a pre-check hit or on the DB unique constraint
    (IntegrityError), so a collision cannot silently overwrite another chat.
    """
    from storage.util import get_utc_iso8601_timestamp

    if not chat.id:
        raise ValueError("chat.id is required for insert")
    if chat_id_exists(user_id, chat.id):
        raise ChatIdCollision(user_id, chat.id)

    chat.update_time = get_utc_iso8601_timestamp()
    content = json.dumps(chat.to_dict())
    title = _extract_title(chat)
    search_text = _extract_search_text(chat)
    status = _chat_status(chat)
    entity = ChatEntity(
        user_id=user_id,
        chat_id=chat.id,
        title=title,
        external_id=chat.external_id,
        backend=chat.backend,
        bot_name=chat.bot_name,
        tier=chat.tier,
        origin_chat_id=chat.origin_chat_id,
        topic=chat.topic,
        skill=chat.skill,
        trace_id=chat.trace_id,
        routine_id=chat.routine_id,
        json_content=content,
        search_text=search_text,
        status=status,
    )
    try:
        with get_db() as session:
            session.add(entity)
    except IntegrityError as exc:
        raise ChatIdCollision(user_id, chat.id) from exc
    return chat


async def insert_chat(user_id: int, chat: Chat) -> Chat:
    return _insert_chat_sync(user_id, chat)


async def add_chat(user_id: int, chat: Chat) -> Chat:
    """Create a chat. Insert-only — collisions raise ChatIdCollision."""
    return await insert_chat(user_id, chat)


async def update_chat(user_id: int, chat: Chat) -> Chat:
    existing = await get_chat(user_id, chat.id)
    if not existing:
        raise ValueError(f"Chat with id {chat.id} not found")
    return await save_chat(user_id, chat)


async def delete_chat(user_id: int, chat_id: str) -> bool:
    with get_db() as session:
        count = session.query(ChatEntity).filter_by(user_id=user_id, chat_id=chat_id).delete()
        return count > 0


def get_chat_meta(user_id: int, chat_id: str) -> Optional[tuple]:
    """Return (chat_id, title) for tag hydration, or None if missing."""
    with get_db() as session:
        row = (
            session.query(ChatEntity.chat_id, ChatEntity.title)
            .filter_by(user_id=user_id, chat_id=chat_id)
            .first()
        )
        if not row:
            return None
        return (row.chat_id, row.title or "")


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


def _resolve_immutable_field(entity: ChatEntity, chat: Chat, field: str):
    """Return the value to write for an immutable-once-set field.

    Rules:
    - entity value is None → take the DTO value (first-time assignment).
    - entity value is set and DTO matches (or is None) → keep entity value.
    - entity value is set and DTO differs → log warning and keep entity value.
    """
    entity_val = getattr(entity, field)
    chat_val = getattr(chat, field)
    if entity_val is None:
        return chat_val
    if chat_val is None or chat_val == entity_val:
        return entity_val
    logger.warning(
        "Refusing to mutate immutable chat field {}: chat_id={} existing={} attempted={}",
        field, chat.id, entity_val, chat_val,
    )
    return entity_val


def _resolve_routing_field(entity: ChatEntity, chat: Chat, field: str):
    """Return the value to write for a re-bottable routing field.

    bot_name and tier follow the bot a chat actually ran on, so a bot change
    accepted by the worker is persisted instead of being refused. An unset DTO
    value still never clears a persisted one: callers that never touched the
    field must not blank it.
    """
    chat_val = getattr(chat, field)
    return chat_val if chat_val else getattr(entity, field)


def _save_chat_sync(user_id: int, chat: Chat) -> Chat:
    from storage.util import get_utc_iso8601_timestamp
    chat.update_time = get_utc_iso8601_timestamp()

    with get_db() as session:
        entity = session.query(ChatEntity).filter_by(user_id=user_id, chat_id=chat.id).first()
        content = json.dumps(chat.to_dict())
        title = _extract_title(chat)
        search_text = _extract_search_text(chat)
        # Derive status from DTO
        if chat.running:
            status = "running"
        elif chat.interrupted:
            status = "interrupted"
        else:
            status = "idle"
        if entity:
            entity.json_content = content
            entity.title = title
            entity.search_text = search_text
            entity.origin_chat_id = chat.origin_chat_id
            entity.external_id = chat.external_id
            entity.backend = _resolve_immutable_field(entity, chat, "backend")
            entity.bot_name = _resolve_routing_field(entity, chat, "bot_name")
            entity.tier = _resolve_routing_field(entity, chat, "tier")
            entity.topic = _resolve_immutable_field(entity, chat, "topic")
            entity.skill = _resolve_immutable_field(entity, chat, "skill")
            entity.trace_id = _resolve_immutable_field(entity, chat, "trace_id")
            entity.routine_id = _resolve_immutable_field(entity, chat, "routine_id")
            entity.status = status
        else:
            entity = ChatEntity(
                user_id=user_id,
                chat_id=chat.id,
                title=title,
                external_id=chat.external_id,
                backend=chat.backend,
                bot_name=chat.bot_name,
                tier=chat.tier,
                origin_chat_id=chat.origin_chat_id,
                topic=chat.topic,
                skill=chat.skill,
                trace_id=chat.trace_id,
                routine_id=chat.routine_id,
                json_content=content,
                search_text=search_text,
                status=status,
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
            logger.exception("Error parsing chat JSON: {}", e)
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
        # Derive status from DTO
        if chat.running:
            status = "running"
        elif chat.interrupted:
            status = "interrupted"
        else:
            status = "idle"
        if entity:
            entity.json_content = content
            entity.title = title
            entity.search_text = search_text
            entity.origin_chat_id = chat.origin_chat_id
            entity.external_id = chat.external_id
            entity.backend = _resolve_immutable_field(entity, chat, "backend")
            entity.bot_name = _resolve_routing_field(entity, chat, "bot_name")
            entity.tier = _resolve_routing_field(entity, chat, "tier")
            entity.topic = _resolve_immutable_field(entity, chat, "topic")
            entity.skill = _resolve_immutable_field(entity, chat, "skill")
            entity.trace_id = _resolve_immutable_field(entity, chat, "trace_id")
            entity.routine_id = _resolve_immutable_field(entity, chat, "routine_id")
            entity.status = status
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


def find_running_chat_ids_older_than(cutoff_unix: int, limit: int = 100) -> List[str]:
    """Return running chat IDs with updated_at_unix older than cutoff_unix."""
    with get_db() as session:
        rows = (session.query(ChatEntity.chat_id)
                .filter(ChatEntity.status == "running")
                .filter(ChatEntity.updated_at_unix < cutoff_unix)
                .order_by(ChatEntity.updated_at_unix.asc())
                .limit(limit)
                .all())
        return [row.chat_id for row in rows]


def list_trace_ids(user_id: int, limit: int = 50, offset: int = 0, trace_id: str = None) -> list:
    """List distinct trace_ids, ordered by most recently updated."""
    from sqlalchemy import func
    with get_db() as session:
        q = (session.query(
                ChatEntity.trace_id,
                func.max(ChatEntity.updated_at).label("updated_at"),
             )
             .filter_by(user_id=user_id)
             .filter(ChatEntity.trace_id.isnot(None)))
        if trace_id:
            q = q.filter(ChatEntity.trace_id.contains(trace_id))
        rows = (q.group_by(ChatEntity.trace_id)
                 .order_by(func.max(ChatEntity.updated_at_unix).desc())
                 .offset(offset)
                 .limit(limit)
                 .all())
        return [
            {"trace_id": row.trace_id, "updated_at": row.updated_at or ""}
            for row in rows
        ]


def release_topic(user_id: int, topic: str, except_chat_id: Optional[str] = None) -> int:
    """Rename `topic` to f'{topic}-archived' on all chats matching (user_id, topic),
    except `except_chat_id`. Returns the affected row count.

    Used to enforce single-owner semantics for root topics (e.g. 'manager') when a
    new chat is about to claim that topic. Direct UPDATE so `_resolve_immutable_field`
    in `_save_chat_*_sync` doesn't apply — otherwise an in-flight worker holding a
    stale DTO with the old topic could silently re-acquire it on its next save.
    """
    with get_db() as session:
        q = session.query(ChatEntity).filter_by(user_id=user_id, topic=topic)
        if except_chat_id:
            q = q.filter(ChatEntity.chat_id != except_chat_id)
        return q.update({"topic": f"{topic}-archived"})


def rename_bot_name(user_id: int, old_name: str, new_name: str) -> int:
    """Rename `bot_name` from `old_name` to `new_name` on all chats matching
    (user_id, bot_name). Returns the affected row count.

    Direct UPDATE so the rename lands on every row in one statement without
    loading and re-saving each chat. Unlike `release_topic` above, this does not
    protect the new name: `bot_name` is a routing field (`_resolve_routing_field`),
    so an in-flight worker holding a stale DTO can write the old name back on its
    next save, after which resolution for that one chat degrades to the tier2
    pool with a warning. Accepted: renames are rare, the window is the few
    hundred ms between a worker's chat load and its next save, and the blast
    radius is a single chat row that the next explicit `--bot` fixes.
    """
    with get_db() as session:
        return (session.query(ChatEntity)
                .filter_by(user_id=user_id, bot_name=old_name)
                .update({"bot_name": new_name}))


def find_chat_by_topic_and_trace(user_id: int, topic: str, trace_id: str) -> Optional[Chat]:
    """Find a chat with the given topic and trace_id."""
    with get_db() as session:
        row = (session.query(ChatEntity)
               .filter_by(user_id=user_id, topic=topic, trace_id=trace_id)
               .order_by(ChatEntity.updated_at_unix.desc())
               .first())
        if row:
            try:
                return _entity_to_chat(row)
            except Exception:
                pass
        return None


def find_chat_by_topic(user_id: int, topic: str) -> Optional[Chat]:
    """Find the most recent chat with the given topic (ignoring trace_id)."""
    with get_db() as session:
        row = (session.query(ChatEntity)
               .filter_by(user_id=user_id, topic=topic)
               .order_by(ChatEntity.updated_at_unix.desc())
               .first())
        if row:
            try:
                return _entity_to_chat(row)
            except Exception:
                pass
        return None


def find_chats_with_messages_by_trace_id(user_id: int, trace_id: str) -> list:
    """Find all chats in a trace, returning (chat_id, title, topic, skill, backend, bot_name, json_content) tuples.
    Includes json_content so caller can extract message-level time segments."""
    with get_db() as session:
        rows = (session.query(ChatEntity)
                .filter_by(user_id=user_id, trace_id=trace_id)
                .order_by(ChatEntity.created_at_unix.asc())
                .all())
        return [
            (row.chat_id, row.title or "", row.topic or "", row.skill or "", row.backend or "", row.bot_name or "", row.json_content)
            for row in rows
        ]


def find_chats_by_trace_id(user_id: int, trace_id: str) -> List[ChatSummary]:
    """Find all chats that participate in a given trace."""
    with get_db() as session:
        rows = (session.query(ChatEntity)
                .filter_by(user_id=user_id, trace_id=trace_id)
                .options(defer(ChatEntity.json_content))
                .order_by(ChatEntity.updated_at_unix.desc())
                .all())
        return [
            ChatSummary(
                chat_id=row.chat_id,
                title=row.title or "",
                created_at=row.created_at or "",
                updated_at=row.updated_at or "",
                topic=row.topic or "",
                skill=row.skill or "",
                routine_id=row.routine_id or "",
                backend=row.backend or "",
                bot_name=row.bot_name or "",
                created_at_unix=row.created_at_unix or 0,
                updated_at_unix=row.updated_at_unix or 0,
                status=row.status or "idle",
                unread=bool(row.unread),
                needs_attention=bool(row.needs_attention),
            )
            for row in rows
        ]


def find_latest_chat_by_topic(user_id: int, topic: Optional[str]) -> Optional[Chat]:
    """Find the most recent chat for a given topic (or topic IS NULL when topic=None)."""
    with get_db() as session:
        q = session.query(ChatEntity).filter_by(user_id=user_id)
        if topic is None:
            q = q.filter(ChatEntity.topic.is_(None))
        else:
            q = q.filter_by(topic=topic)
        row = q.order_by(ChatEntity.updated_at_unix.desc()).first()
        if not row:
            return None
        try:
            return _entity_to_chat(row)
        except Exception as e:
            logger.exception("Error parsing chat JSON: {}", e)
            return None


def find_latest_chat_by_trace_id(user_id: int, trace_id: str) -> Optional[Chat]:
    """Find the most recent chat for a given trace_id."""
    with get_db() as session:
        row = (session.query(ChatEntity)
               .filter_by(user_id=user_id, trace_id=trace_id)
               .order_by(ChatEntity.updated_at_unix.desc())
               .first())
        if not row:
            return None
        try:
            return _entity_to_chat(row)
        except Exception as e:
            logger.exception("Error parsing chat JSON: {}", e)
            return None


def get_trace_chat_status(user_id: int, trace_ids: list) -> dict:
    """Return {trace_id: {"has_running": bool, "has_unread": bool}} for given trace_ids."""
    from sqlalchemy import func, case
    if not trace_ids:
        return {}
    with get_db() as session:
        rows = (session.query(
                    ChatEntity.trace_id,
                    func.max(case((ChatEntity.status == "running", 1), else_=0)).label("has_running"),
                    func.max(case((ChatEntity.unread == True, 1), else_=0)).label("has_unread"),
                )
                .filter_by(user_id=user_id)
                .filter(ChatEntity.trace_id.in_(trace_ids))
                .group_by(ChatEntity.trace_id)
                .all())
        return {
            row.trace_id: {"has_running": bool(row.has_running), "has_unread": bool(row.has_unread)}
            for row in rows
        }


def set_chat_unread(chat_id: str, unread: bool) -> None:
    """Set the unread column on a chat without touching updated_at.

    Uses raw SQL so SQLAlchemy's column-level onupdate=get_utc_iso8601_timestamp
    on BaseEntity.updated_at / updated_at_unix is bypassed; otherwise marking a
    chat read/unread would bump it to the top of the chat list.
    """
    with get_db() as session:
        session.execute(
            text("UPDATE chat SET unread = :unread WHERE chat_id = :chat_id AND unread IS DISTINCT FROM :unread"),
            {"unread": unread, "chat_id": chat_id},
        )


def set_chat_attention(user_id: int, chat_id: str, needs_attention: bool) -> None:
    """Set the needs_attention column on a chat without touching updated_at.

    Mirrors set_chat_unread: raw SQL so the attention-only write never bumps a
    chat to the top of the recency-ordered list on its own. `(user_id,
    chat_id)` is unique, `chat_id` alone is not (public chat ids are only
    unique per user), so the predicate must include user_id or this can hit
    another user's same-id chat.
    """
    with get_db() as session:
        session.execute(
            text(
                "UPDATE chat SET needs_attention = :needs_attention "
                "WHERE user_id = :user_id AND chat_id = :chat_id "
                "AND needs_attention IS DISTINCT FROM :needs_attention"
            ),
            {"needs_attention": needs_attention, "user_id": user_id, "chat_id": chat_id},
        )


def clear_attention_and_unread(user_id: int, chat_id: str) -> None:
    """Clear both needs_attention and unread without touching updated_at.

    Used when a new user message is accepted into an existing chat: replying
    resolves whatever the chat was waiting on or announcing, so both signals
    reset atomically in one statement rather than two separate writes.
    user_id is required for the same reason as set_chat_attention above.
    """
    with get_db() as session:
        session.execute(
            text(
                "UPDATE chat SET needs_attention = false, unread = false "
                "WHERE user_id = :user_id AND chat_id = :chat_id "
                "AND (needs_attention = true OR unread = true)"
            ),
            {"user_id": user_id, "chat_id": chat_id},
        )


def mark_completion_unread(user_id: int, chat_id: str) -> None:
    """Mark unread on successful completion, unless the chat already needs attention.

    needs_attention is the stronger state: an agent that called `y chat
    attention` mid-turn to signal it is blocked on Roy must not have that
    immediately downgraded to a plain unread by the same turn's completion
    hook. The WHERE clause makes "only when not already blocked" atomic
    instead of a read-then-write race with the producer command. user_id is
    required for the same reason as set_chat_attention above; the worker
    already has it on every completion path (proc/messages carry it).
    """
    with get_db() as session:
        session.execute(
            text(
                "UPDATE chat SET unread = true "
                "WHERE user_id = :user_id AND chat_id = :chat_id "
                "AND needs_attention = false AND unread = false"
            ),
            {"user_id": user_id, "chat_id": chat_id},
        )


def mark_chats_read_by_trace(user_id: int, trace_id: str) -> int:
    """Mark all chats with the given trace_id as read without touching updated_at."""
    with get_db() as session:
        result = session.execute(
            text("UPDATE chat SET unread = false WHERE user_id = :user_id AND trace_id = :trace_id AND unread = true"),
            {"user_id": user_id, "trace_id": trace_id},
        )
        return result.rowcount or 0


def mark_chats_read_by_trace_ids(user_id: int, trace_ids: list) -> int:
    """Bulk-mark chats as read for the given trace_ids without touching updated_at."""
    if not trace_ids:
        return 0
    from sqlalchemy import bindparam
    with get_db() as session:
        stmt = text(
            "UPDATE chat SET unread = false "
            "WHERE user_id = :user_id AND unread = true AND trace_id IN :trace_ids"
        ).bindparams(bindparam("trace_ids", expanding=True))
        result = session.execute(stmt, {"user_id": user_id, "trace_ids": list(trace_ids)})
        return result.rowcount or 0


def mark_latest_chat_unread_by_trace(user_id: int, trace_id: str) -> Optional[str]:
    """Mark the most recently updated chat in the trace as unread without touching updated_at.

    Returns its chat_id, or None if no chats."""
    with get_db() as session:
        row = (session.query(ChatEntity.chat_id)
               .filter_by(user_id=user_id, trace_id=trace_id)
               .order_by(ChatEntity.updated_at_unix.desc())
               .first())
        if not row:
            return None
        chat_id = row.chat_id
        session.execute(
            text("UPDATE chat SET unread = true WHERE user_id = :user_id AND chat_id = :chat_id AND unread = false"),
            {"user_id": user_id, "chat_id": chat_id},
        )
        return chat_id


def get_share_password_hash(user_id: int, chat_id: str) -> Optional[str]:
    with get_db() as session:
        row = (session.query(ChatEntity.share_password_hash)
               .filter_by(user_id=user_id, chat_id=chat_id)
               .first())
        return row[0] if row else None


def set_share_password_hash(user_id: int, chat_id: str, password_hash: Optional[str]) -> None:
    with get_db() as session:
        session.query(ChatEntity).filter_by(user_id=user_id, chat_id=chat_id).update(
            {"share_password_hash": password_hash}
        )
