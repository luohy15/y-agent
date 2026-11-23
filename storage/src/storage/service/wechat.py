import hmac
import secrets
import time

from sqlalchemy import delete, func, select, text

from loguru import logger

from storage.database.base import get_db
from storage.entity.wechat import (
    WechatAccountEntity as Account, WechatContextEntity as Context,
    WechatInboundEntity as Inbound, WechatOutboxEntity as Outbox, WechatPeerEntity as Peer,
)
from storage.repository.wechat import bridge_account, digest, locked_account, peer_for
from storage.service.user_access import request_admitted, resolve_maintainer


class ChannelError(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


def is_operator(user_id):
    return user_id is not None and resolve_maintainer()["internal_id"] == user_id


def operator(user_id):
    if not is_operator(user_id):
        raise ChannelError(403, "Binding requires the admitted maintainer's own account")


def bind(user_id, account, peer, bot_token):
    operator(user_id)
    secret = secrets.token_urlsafe(40)
    code = f"{secrets.randbelow(1000000):06d}"
    with get_db() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(4400, 1)"))
        old = locked_account(db)
        if old:
            if old.user_id != user_id:
                raise ChannelError(403, "Not the binding owner")
            db.delete(old)
            db.flush()
        db.add(Account(slot=1, account=account, user_id=user_id, status="active",
                       bot_token=bot_token, bridge_hash=digest(secret)))
        db.flush()
        db.add(Peer(account=account, peer=peer, user_id=user_id, generation=secrets.token_hex(16),
                    code_hash=digest(code), expires=int(time.time()) + 600, status="pending"))
    return {"bridge_token": secret, "code": code}


def _summary(db, account, peer):
    now = int(time.time())
    return {
        "account": account.account, "peer": peer.peer, "status": peer.status,
        "heartbeat": account.heartbeat, "last_poll": account.last_poll,
        "heartbeat_age_seconds": now - account.heartbeat if account.heartbeat is not None else None,
        "last_poll_age_seconds": now - account.last_poll if account.last_poll is not None else None,
        "available": _available(account, peer, now),
        "last_error": account.last_error, "last_delivery_error": account.last_error,
        "outbox": dict(db.execute(select(Outbox.status, func.count()).where(
            Outbox.account == account.account).group_by(Outbox.status)).all()),
    }


def channel_summary(user_id):
    operator(user_id)
    with get_db() as db:
        account = db.scalar(select(Account).filter_by(user_id=user_id))
        peer = peer_for(db, account) if account else None
        if not peer or peer.user_id != user_id:
            return {"status": "unbound"}
        return _summary(db, account, peer)


def owner_state(user_id, action):
    if action == "status":
        return channel_summary(user_id)
    operator(user_id)
    with get_db() as db:
        account = locked_account(db)
        if not account or account.user_id != user_id:
            return {"status": "unbound"}
        peer = peer_for(db, account)
        if action == "unbind":
            account.status = peer.status = "revoked"
            account.bridge_hash = account.bot_token = peer.code_hash = None
            for model in (Context, Outbox):
                db.execute(delete(model).where(model.account == account.account))
        return _summary(db, account, peer)


def verify_code(peer, value, now):
    valid = peer.expires > now and hmac.compare_digest(peer.code_hash or "", digest(value))
    peer.code_hash = None
    peer.status = "active" if valid else "revoked"
    return valid


WECHAT_BRIDGE_STALE_SECONDS = 300


def admitted(user_id):
    return request_admitted(user_id, None)["admitted"]


def bridge_live(heartbeat, now):
    if isinstance(heartbeat, bool) or not isinstance(heartbeat, int):
        return False
    age = now - heartbeat
    return 0 <= age < WECHAT_BRIDGE_STALE_SECONDS


def _available(account, peer, now):
    return (account.status == "active" and bridge_live(account.heartbeat, now)
            and peer is not None and peer.user_id == account.user_id and peer.status == "active")


def _notify_target(db, user_id, now, *, lock=True):
    account = locked_account(db) if lock else db.scalar(select(Account).filter_by(user_id=user_id))
    if not account or account.user_id != user_id:
        return None
    peer = peer_for(db, account)
    if not _available(account, peer, now):
        return None
    return account, peer


def notify_available(user_id):
    try:
        with get_db() as db:
            return _notify_target(db, user_id, int(time.time()), lock=False) is not None
    except Exception:
        logger.exception("wechat notify availability failed user_id={}", user_id)
        return False


def notify_user(user_id, text):
    """Queue a proactive text for the owner. No maintainer gate. Never raises."""
    if not isinstance(text, str) or not text.strip():
        return False
    now = int(time.time())
    try:
        with get_db() as db:
            target = _notify_target(db, user_id, now)
            if not target:
                return False
            account, peer = target
            enqueue(db, account, peer.peer, text, secrets.token_hex(16))
        return True
    except ChannelError:
        return False
    except Exception:
        logger.exception("wechat notify failed user_id={}", user_id)
        return False


def authenticate(db, token):
    row = bridge_account(db, token)
    if not row:
        raise ChannelError(401, "Invalid bridge token")
    return row


def context_for(db, account, peer):
    return db.scalar(select(Context).filter_by(account=account.account, peer=peer))


async def inbound(db, account, message_id, peer, text, context_token, media):
    from storage.dto.chat import Chat
    from storage.repository import chat as chat_repo
    from storage.service import chat as chats
    from storage.service.reply_route import split_chat_route
    from storage.util import get_utc_iso8601_timestamp

    if db.get(Inbound, (account.account, message_id)):
        return {"result": "duplicate"}
    now = int(time.time())
    recent = db.scalar(select(func.count()).select_from(Inbound).where(
        Inbound.account == account.account, Inbound.peer == peer,
        Inbound.created_at_unix >= (now - 60) * 1000))
    receipt = Inbound(account=account.account, message_id=message_id, peer=peer)
    db.add(receipt)
    if recent >= 30:
        return {"result": "rate_limited"}
    binding = peer_for(db, account)
    if not admitted(account.user_id):
        return {"result": "not_admitted"}
    event = digest(f"{binding.generation}:{message_id}")
    if context_token:
        context = context_for(db, account, peer)
        if not context:
            context = Context(key=secrets.token_hex(16), account=account.account,
                              peer=peer, user_id=account.user_id)
            db.add(context)
        context.context_token = context_token
        for row in db.scalars(select(Outbox).filter_by(account=account.account, peer=peer, status="blocked_on_context")):
            row.status = "pending"
    if binding.peer != peer or binding.status == "revoked":
        notice = "This WeChat account is not bound."
    elif binding.status == "pending":
        notice = ("Binding confirmed." if verify_code(binding, text.strip(), now)
                  else "Binding code invalid or expired. Start a new login.")
    elif media or not text.strip():
        notice = "Text messages only for now."
    else:
        routed_id, routed_body = split_chat_route(text, skip_leading_quotes=True)
        if routed_id:
            target = await chat_repo.get_chat(account.user_id, routed_id)
            if not target:
                notice = f"chat /{routed_id} not found"
            else:
                try:
                    accepted = await chats.accept_user_message(
                        account.user_id, target, routed_body, source="wechat",
                        human_reply=True, session=db,
                        event_id=f"wc_{binding.generation}_{event}")
                    if not accepted.already_running:
                        receipt.enqueue_chat = accepted.chat.id
                        receipt.enqueue_seq = accepted.chat.run_seq
                    return {"result": "accepted"}
                except chats.resume_gate.ChatReadOnly:
                    notice = "This conversation is read-only. Send /clear to start a new one."
        else:
            reset = text.strip() in {"/clear", "/new"}
            chat = chat_repo.find_latest_chat_by_role(account.user_id, "manager")
            if not chat or reset:
                timestamp = get_utc_iso8601_timestamp()
                chat = Chat(id=chats.new_chat_id(account.user_id), role="manager", messages=[],
                            create_time=timestamp, update_time=timestamp, running=False)
                chat_repo._insert_chat_sync(account.user_id, chat, session=db)
                chat_repo.release_role(account.user_id, "manager", except_chat_id=chat.id, session=db)
            try:
                accepted = await chats.accept_user_message(
                    account.user_id, chat, "load manager skill" if reset else text, role="manager",
                    source=None if reset else "wechat", human_reply=True, session=db,
                    event_id=f"wc_{binding.generation}_{event}")
                if not accepted.already_running:
                    receipt.enqueue_chat = accepted.chat.id
                    receipt.enqueue_seq = accepted.chat.run_seq
                if not reset:
                    return {"result": "accepted"}
                notice = "Started a new manager conversation."
            except chats.resume_gate.ChatReadOnly:
                notice = "This conversation is read-only. Send /clear to start a new one."
    enqueue(db, account, peer, notice, event)
    return {"result": "notice"}


async def deliver_receipt(token, message_id):
    from storage.repository import chat as chat_repo
    from storage.service.chat import send_chat_message

    with get_db() as db:
        account = authenticate(db, token)
        receipt = db.get(Inbound, (account.account, message_id))
        if not receipt or not receipt.enqueue_chat:
            return
        chat_id = receipt.enqueue_chat
        run_seq = receipt.enqueue_seq
        user_id = account.user_id
        chat = await chat_repo.get_chat(user_id, chat_id)
        send_chat_message(
            chat_id, user_id=user_id, run_seq=run_seq,
            role=getattr(chat, "role", None), skill=getattr(chat, "skill", None),
            trace_id=getattr(chat, "trace_id", None), work_dir=getattr(chat, "work_dir", None),
        )
        receipt.enqueue_chat = None


def enqueue(db, account, peer, body, key):
    from storage.service.wechat_format import chunks

    parts = chunks(body)
    if db.scalar(select(Outbox.seq).filter_by(outbox_id=digest(f"{key}:0"))):
        return
    queued = db.scalar(select(func.count()).select_from(Outbox).where(
        Outbox.account == account.account, Outbox.peer == peer,
        Outbox.status.not_in(("sent", "failed"))))
    if queued + len(parts) > 100:
        raise ChannelError(429, "Peer outbox full")
    context = context_for(db, account, peer)
    status = "pending" if context and context.context_token else "blocked_on_context"
    for index, part in enumerate(parts):
        db.add(Outbox(account=account.account, peer=peer, user_id=account.user_id,
                      outbox_id=digest(f"{key}:{index}"), text=part, status=status))


def send(user_id, body):
    operator(user_id)
    with get_db() as db:
        account = locked_account(db)
        if not account or account.user_id != user_id or account.status != "active":
            raise ChannelError(409, "No active bot")
        peer = peer_for(db, account)
        if peer.status != "active":
            raise ChannelError(409, "No active binding")
        enqueue(db, account, peer.peer, body, secrets.token_hex(16))
        return {"ok": True}


def enqueue_reply(chat, user_id):
    if chat.role != "manager":
        return
    reply = None
    for message in reversed(chat.messages):
        if message.role == "user":
            break
        if not reply and message.role == "assistant" and isinstance(message.content, str) and message.content.strip():
            reply = message
    else:
        return
    if not reply or message.source != "wechat" or not message.id:
        return
    with get_db() as db:
        account = locked_account(db)
        if not account or account.status != "active" or account.user_id != user_id:
            return
        peer = peer_for(db, account)
        if peer.status == "active" and message.id.startswith(f"msg_evt_wc_{peer.generation}_"):
            enqueue(db, account, peer.peer, reply.content, f"{chat.id}:{reply.id}:{message.id}")


def claim(db, account):
    if not admitted(account.user_id):
        raise ChannelError(403, "Admission revoked")
    now = int(time.time())
    rows = db.scalars(select(Outbox).where(Outbox.account == account.account,
                      Outbox.status.in_(("pending", "leased"))).order_by(Outbox.seq))
    waiting = set()
    for row in rows:
        if row.peer in waiting:
            continue
        if row.available > now:
            waiting.add(row.peer)
            continue
        if row.attempts >= 5:
            row.status = "failed"
            account.last_error = "lease_attempts_exhausted"
            continue
        context = context_for(db, account, row.peer)
        if not context or not context.context_token:
            row.status = "blocked_on_context"
            continue
        row.lease = secrets.token_hex(16)
        row.status = "leased"
        row.attempts += 1
        row.available = now + 60
        return {"item": {"outbox_id": row.outbox_id, "lease": row.lease, "text": row.text,
                         "peer": row.peer, "context_token": context.context_token}}
    return {"item": None}


def finish(row, ok, now):
    row.lease = None
    row.status = "sent" if ok else ("failed" if row.attempts >= 5 else "pending")
    row.available = now + 2 ** row.attempts if row.status == "pending" else 0


def ack(db, account, outbox_id, lease, ok):
    row = db.scalar(select(Outbox).filter_by(account=account.account, outbox_id=outbox_id))
    if not row or row.status != "leased" or not secrets.compare_digest(row.lease or "", lease):
        raise ChannelError(409, "Stale lease")
    finish(row, ok, int(time.time()))
    if not ok:
        account.last_error = "send_attempts_exhausted" if row.status == "failed" else "send_rejected"
    return {"ok": True}
