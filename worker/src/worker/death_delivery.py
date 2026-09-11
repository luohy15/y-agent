"""Owner-bound terminal failure persistence and delivery. No success hooks."""
import json
import re

from loguru import logger

from storage.service import chat as chat_service
from worker.process_manager import get_process, get_running_processes


def current_run(chat_id, proc):
    current = get_process(chat_id)
    return bool(proc.get("started_at") and current.get("started_at") == proc["started_at"]
                and current.get("user_id") == proc["user_id"]
                and current.get("trace_id") == proc.get("trace_id"))


def parent_id(chat):
    first = next((m for m in chat.messages if m.role == "user"), None)
    if not first or not isinstance(first.content, str):
        return None
    line = first.content.split("\n", 1)[0]
    if not re.fullmatch(r"\[(?:[a-z_]+:[^\s\[\]]+)(?: [a-z_]+:[^\s\[\]]+)*\]", line):
        return None
    pairs = [part.split(":", 1) for part in line[1:-1].split(" ")]
    fields = dict(pairs)
    if len(fields) != len(pairs):
        return None
    target = fields.get("from_chat")
    if (fields.get("trace") != chat.trace_id or fields.get("to_chat") != chat.id
            or not target or target == chat.id):
        return None
    return target


async def persist_terminal(chat_id, proc, result, outcome="error"):
    """Serialize against accepts, reload messages, reject obsolete completions."""
    from storage.database.base import get_db
    from storage.entity.chat import ChatEntity
    from storage.repository.todo import lock_todo
    from storage.repository.chat import _entity_to_chat, _extract_search_text, _chat_status
    from storage.util import get_utc_iso8601_timestamp
    from worker.monitor import _apply_completion_metadata

    with get_db() as session:
        lock_todo(session, proc["user_id"], proc.get("trace_id"))
        row = session.query(ChatEntity).filter_by(
            user_id=proc["user_id"], chat_id=chat_id).with_for_update().first()
        if (not row or (row.topic != "manager" and row.trace_id != proc.get("trace_id"))
                or not current_run(chat_id, proc)):
            return None
        from worker.process_manager import complete_current_process
        if outcome is not None and not complete_current_process(chat_id, proc, outcome):
            return None
        chat = _entity_to_chat(row)
        chat.running = outcome is None and not chat.interrupted
        await _apply_completion_metadata(chat, result, result.get("result_data"), proc, chat_id)
        chat.update_time = get_utc_iso8601_timestamp()
        row.json_content = json.dumps(chat.to_dict())
        row.external_id = chat.external_id
        row.status = _chat_status(chat)
        row.search_text = _extract_search_text(chat)
        return chat


async def deliver_death(chat_id, proc, outcome, error):
    from storage.service import todo as todo_service
    from storage.service.telegram import resolve_target
    from storage.util import send_telegram_message_checked
    from storage.entity.chat import ChatEntity

    user_id = proc["user_id"]
    chat = await chat_service.get_chat(user_id, chat_id)
    if (not chat or (chat.topic != "manager" and chat.trace_id != proc.get("trace_id")) or chat.running
            or not current_run(chat_id, proc)):
        return "obsolete"
    chat_service.mark_chat_completion_unread(user_id, chat_id)
    text = f"Trace {chat.trace_id or 'unknown'}, child {chat_id}: observed {outcome}. {str(error or 'No error detail available.')[:1800]}"
    if chat.topic == "manager":
        try:
            target = resolve_target(user_id, topic=chat.topic)
            if target and send_telegram_message_checked(target[0], target[1], text):
                return "topic"
        except Exception:
            logger.warning("Death topic delivery failed: chat_id={}", chat_id)
    else:
        target_id = parent_id(chat)
        parent = await chat_service.get_chat(user_id, target_id) if target_id else None
        if parent and parent.trace_id == chat.trace_id and parent.topic != "manager":
            try:
                await chat_service.deliver_dispatch(
                    user_id, parent, text, trace_id=chat.trace_id,
                    from_chat_id=chat_id, from_topic=chat.topic, topic=parent.topic,
                    work_dir=parent.work_dir,
                )
                return "parent"
            except Exception:
                logger.warning("Death parent delivery failed: chat_id={}", chat_id)
    if not chat.trace_id:
        return "no-trace"
    todo = todo_service.get_todo(user_id, chat.trace_id)
    if not todo:
        return "no-todo"

    from storage.repository import dev_release as dev_release_repo

    def recheck(session, row):
        # A pending publication-slot registration on this trace is an explained
        # wait, not unexplained silence (todo 3506 S2: no more awaiting=external
        # park write, the watchdog/death path reads the waiter table directly).
        if dev_release_repo.has_pending_waiter(session, user_id, chat.trace_id):
            return None
        if not current_run(chat_id, proc):
            return None
        rows = session.query(ChatEntity).filter_by(user_id=user_id, trace_id=chat.trace_id).all()
        ids = {r.chat_id for r in rows}
        for record in get_running_processes():
            if record.get("user_id") == user_id and (
                record.get("trace_id") == chat.trace_id or record.get("chat_id") in ids
            ):
                return None
        if any(r.chat_id != chat_id and (r.updated_at_unix or 0) >= proc["started_at"] * 1000 for r in rows):
            return None
        return text, chat_id

    try:
        _todo, changed = todo_service.claim_fault(
            user_id, chat.trace_id, expected_updated_at_unix=todo.updated_at_unix, recheck=recheck,
        )
        return "inbox" if changed else "suppressed"
    except Exception:
        logger.exception("Death inbox evidence or delivery failed: chat_id={}", chat_id)
    return "suppressed"
