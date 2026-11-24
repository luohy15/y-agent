"""Private per-user todo grants and public-todo visit history."""

from typing import Dict, List, Optional

from loguru import logger

from storage.crypto.blob import note_object_key
from storage.database.base import get_db
from storage.entity.chat import ChatEntity
from storage.entity.user import UserEntity
from storage.repository import link as link_repo
from storage.repository import link_todo_relation as link_relation_repo
from storage.repository import note as note_repo
from storage.repository import note_todo_relation as note_relation_repo
from storage.repository import todo as todo_repo
from storage.repository import todo_share as share_repo
from storage.repository import todo_visit as visit_repo
from storage.repository import trace_share as trace_share_repo
from storage.repository import user as user_repo
from storage.service import gateway as gateway_service
from storage.service.user_access import admission_state, normalize_email
from storage.util import generate_id


class TodoShareError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def shared_row(todo, share_id: str, shared_at: str, owner_label: str) -> Dict:
    """Recipient payload. Operational fields stay off the dict."""
    tags = list(todo.tags) if todo.tags is not None else None
    return {
        "share_id": share_id,
        "name": todo.name,
        "desc": todo.desc,
        "status": todo.status,
        "priority": todo.priority,
        "due_date": todo.due_date,
        "sla_due_at": todo.sla_due_at,
        "tags": tags,
        "progress": todo.progress,
        "completed_at": todo.completed_at,
        "owner": owner_label,
        "shared_at": shared_at,
    }


def note_title(note) -> str:
    matter = note.front_matter if note and isinstance(note.front_matter, dict) else {}
    title = matter.get("title") if isinstance(matter, dict) else None
    if isinstance(title, str) and title.strip():
        return title.strip()
    stem = ""
    if note and note.content_key:
        stem = note.content_key.rstrip("/").split("/")[-1]
        if stem.endswith(".md"):
            stem = stem[:-3]
    if stem:
        return stem
    return note.note_id if note else ""


def lookup_recipient(owner_id: int, to: str, *, admit: bool) -> UserEntity:
    token = (to or "").strip()
    if not token:
        raise TodoShareError(422, "Recipient not found")
    if "@" in token:
        user = user_repo.get_user_by_normalized_email(normalize_email(token))
    else:
        user = user_repo.get_user_by_user_id(token)
    if user is None:
        raise TodoShareError(422, "Recipient not found")
    if user.id == owner_id:
        raise TodoShareError(422, "Cannot share a todo with yourself")
    if admit and admission_state(user.email or "") != "approved":
        raise TodoShareError(422, "Recipient is not admitted")
    return user


def _labels(user_ids: List[int]) -> Dict[int, str]:
    if not user_ids:
        return {}
    with get_db() as session:
        rows = session.query(UserEntity).filter(
            UserEntity.id.in_(set(user_ids)),
            UserEntity.deleted.is_(False),
        ).all()
        return {row.id: (row.email or row.user_id or "") for row in rows}


def _owner_label(owner_id: int) -> str:
    return _labels([owner_id]).get(owner_id, "")


def related_ids(owner_id: int, todo_id: str) -> Dict[str, set]:
    note_ids = note_relation_repo.list_by_todo(owner_id, todo_id)
    live_notes = {note.note_id for note in note_repo.get_notes_by_ids(owner_id, note_ids)}
    with get_db() as session:
        chat_ids = {
            row[0]
            for row in session.query(ChatEntity.chat_id).filter_by(user_id=owner_id, trace_id=todo_id).all()
        }
    activity_ids = link_relation_repo.list_by_todo(owner_id, todo_id)
    live_links = {row.activity_id for row in link_repo.get_links_by_activity_ids(owner_id, activity_ids)}
    return {"note": live_notes, "chat": chat_ids, "link": live_links}


def _expand(requested: Optional[List[str]], related: set) -> List[str]:
    values = requested or []
    if any(item == "all" for item in values):
        if any(item != "all" for item in values):
            raise TodoShareError(422, "Unknown or unrelated item")
        return sorted(related)
    chosen = []
    seen = set()
    for raw in values:
        ref = (raw or "").strip()
        if not ref or ref not in related or ref in seen:
            if ref in seen:
                continue
            raise TodoShareError(422, "Unknown or unrelated item")
        seen.add(ref)
        chosen.append(ref)
    return chosen


def _materialize(owner_id: int, note_ids: List[str], chat_ids: List[str], link_ids: List[str]) -> List[Dict]:
    notes = {note.note_id: note for note in note_repo.get_notes_by_ids(owner_id, note_ids)}
    items = []
    for ref in note_ids:
        note = notes.get(ref)
        if note is None:
            raise TodoShareError(422, "Unknown or unrelated item")
        items.append({"kind": "note", "ref_id": ref, "content_key": note.content_key})
    for ref in chat_ids:
        items.append({"kind": "chat", "ref_id": ref})
    for ref in link_ids:
        items.append({"kind": "link", "ref_id": ref})
    return items


def _selection_items(owner_id: int, todo_id: str, notes, chats, links) -> List[Dict]:
    related = related_ids(owner_id, todo_id)
    return _materialize(
        owner_id,
        _expand(notes, related["note"]),
        _expand(chats, related["chat"]),
        _expand(links, related["link"]),
    )


def _live_todo(owner_id: int, todo_id: str):
    todo = todo_repo.get_todo(owner_id, (todo_id or "").strip())
    if todo is None or todo.status == "deleted":
        raise TodoShareError(404, "Todo not found")
    return todo


def prepare_share(owner_id: int, todo_id: str, to: str, notes, chats, links, clear_items: bool) -> Dict:
    if clear_items and any(value is not None for value in (notes, chats, links)):
        raise TodoShareError(422, "clear_items cannot be combined with a selection")
    recipient = lookup_recipient(owner_id, to, admit=True)
    todo = _live_todo(owner_id, todo_id)
    pair = share_repo.get_pair(owner_id, todo.todo_id, recipient.id, include_revoked=True)
    if clear_items or notes is not None or chats is not None or links is not None:
        items = _selection_items(
            owner_id,
            todo.todo_id,
            [] if clear_items else notes,
            [] if clear_items else chats,
            [] if clear_items else links,
        )
    else:
        existing = share_repo.list_items(pair["share_id"]) if pair else []
        grouped = {"note": [], "chat": [], "link": []}
        for item in existing:
            if item["kind"] not in grouped:
                raise TodoShareError(422, "Unknown or unrelated item")
            grouped[item["kind"]].append(item["ref_id"])
        items = _selection_items(owner_id, todo.todo_id, grouped["note"], grouped["chat"], grouped["link"])
    return {
        "share_id": pair["share_id"] if pair else generate_id(),
        "recipient_id": recipient.id,
        "todo_id": todo.todo_id,
        "todo_name": todo.name,
        "owner_label": _owner_label(owner_id),
        "items": items,
    }


def snapshot_items(owner_id: int, share_id: str, items: List[Dict]) -> List[Dict]:
    with get_db() as session:
        keyed = []
        for item in items:
            key = None
            if item["kind"] == "note":
                key = note_object_key(owner_id, f"_todo_share/{share_id}/note-{item['ref_id']}", session)
            keyed.append({"kind": item["kind"], "ref_id": item["ref_id"], "snapshot_key": key})
        return keyed


def save_share(owner_id: int, recipient_id: int, todo_id: str, share_id: str, items: List[Dict]) -> Dict:
    _live_todo(owner_id, todo_id)
    return share_repo.save_grant(owner_id, todo_id, recipient_id, share_id, items)


def notify_share(recipient_id: int, owner_label: str, todo_name: str) -> bool:
    who = owner_label or "Someone"
    name = todo_name or "a todo"
    try:
        return bool(gateway_service.send(recipient_id, f"{who} shared a todo with you: {name}"))
    except Exception:
        logger.exception("todo share notice failed user_id={}", recipient_id)
        return False


def revoke_share(owner_id: int, todo_id: str, to: str) -> Dict:
    recipient = lookup_recipient(owner_id, to, admit=False)
    revoked = share_repo.revoke(owner_id, (todo_id or "").strip(), recipient.id)
    if revoked is None:
        raise TodoShareError(404, "Share not found")
    return revoked


def _hydrate(rows: List[Dict], *, label_key: str) -> List[Dict]:
    if not rows:
        return []
    by_owner: Dict[int, List[str]] = {}
    for row in rows:
        by_owner.setdefault(row["owner_id"], [])
        if row["todo_id"] not in by_owner[row["owner_id"]]:
            by_owner[row["owner_id"]].append(row["todo_id"])
    todos = {
        owner_id: todo_repo.find_todos_by_ids(owner_id, ids) if ids else {}
        for owner_id, ids in by_owner.items()
    }
    labels = _labels([row[label_key] for row in rows])
    result = []
    for row in rows:
        todo = todos.get(row["owner_id"], {}).get(row["todo_id"])
        if todo is None or todo.status == "deleted":
            continue
        result.append((row, todo, labels))
    return result


def list_shared(recipient_id: int) -> List[Dict]:
    rows = share_repo.list_incoming(recipient_id)
    hydrated = _hydrate(rows, label_key="owner_id")
    return [
        shared_row(todo, row["share_id"], row["shared_at"], labels.get(row["owner_id"], ""))
        for row, todo, labels in hydrated
    ]


def shared_detail(recipient_id: int, share_id: str) -> Optional[Dict]:
    row = share_repo.get_visible_incoming(recipient_id, (share_id or "").strip())
    if row is None:
        return None
    hydrated = _hydrate([row], label_key="owner_id")
    if not hydrated:
        return None
    stored, todo, labels = hydrated[0]
    return {
        "owner_id": stored["owner_id"],
        "todo_id": stored["todo_id"],
        "todo": shared_row(todo, stored["share_id"], stored["shared_at"], labels.get(stored["owner_id"], "")),
        "items": share_repo.list_items(stored["share_id"]),
    }


def list_outgoing(owner_id: int) -> List[Dict]:
    rows = share_repo.list_outgoing(owner_id)
    if not rows:
        return []
    todos = todo_repo.find_todos_by_ids(owner_id, list({row["todo_id"] for row in rows}))
    labels = _labels([row["recipient_id"] for row in rows])
    grouped = share_repo.list_items_for([row["share_id"] for row in rows])
    result = []
    for row in rows:
        todo = todos.get(row["todo_id"])
        if todo is None or todo.status == "deleted":
            continue
        result.append({
            "share_id": row["share_id"],
            "todo_id": row["todo_id"],
            "name": todo.name,
            "recipient": labels.get(row["recipient_id"], ""),
            "shared_at": row["shared_at"],
            "items": [
                {"kind": item["kind"], "ref_id": item["ref_id"]}
                for item in grouped.get(row["share_id"], [])
            ],
        })
    return result


def list_public(user_id: int) -> List[Dict]:
    rows = visit_repo.list_live(user_id)
    hydrated = _hydrate(rows, label_key="owner_id")
    return [
        {
            "share_id": row["share_id"],
            "name": todo.name,
            "status": todo.status,
            "last_visited_at": row["visited_at"],
        }
        for row, todo, _labels in hydrated
    ]


def summary(user_id: int) -> Dict:
    return {"shared": len(list_shared(user_id)), "public": len(list_public(user_id))}


def record_visit(user_id: int, share_id: str) -> Dict:
    token = (share_id or "").strip()
    if not token:
        raise TodoShareError(404, "Share not found")
    share = trace_share_repo.get_by_share_id(token)
    if share is None or share.revoked_at:
        raise TodoShareError(404, "Share not found")
    if share.user_id == user_id:
        return {"recorded": False}
    todo = todo_repo.get_todo(share.user_id, share.trace_id)
    if todo is None or todo.status == "deleted":
        return {"recorded": False}
    visit_repo.record(user_id, token)
    return {"recorded": True}
