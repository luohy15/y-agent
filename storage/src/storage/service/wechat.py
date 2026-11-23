import hmac
import secrets
import time

from sqlalchemy import delete, func, select, text

from storage.database.base import get_db
from storage.entity.wechat import (
    WechatAccountEntity as Account, WechatContextEntity as Context,
    WechatInboundEntity as Inbound, WechatOutboxEntity as Outbox, WechatPeerEntity as Peer,
)
from storage.repository.wechat import bridge_account, digest, locked_account, peer_for
from storage.service.user_access import normalize_email, request_admitted, resolve_maintainer


class ChannelError(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


def operator(user_id, email=None):
    maintainer = resolve_maintainer()
    if maintainer["internal_id"] != user_id or (email is not None and normalize_email(email) != maintainer["email"]):
        raise ChannelError(403, "Binding requires the admitted maintainer's own account")


def bind(user_id, email, account, peer, bot_token):
    operator(user_id, email)
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


def owner_state(user_id, action):
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
        return {"status": peer.status, "heartbeat": account.heartbeat, "last_poll": account.last_poll,
                "last_delivery_error": account.last_error,
                "outbox": dict(db.execute(select(Outbox.status, func.count()).where(
                    Outbox.account == account.account).group_by(Outbox.status)).all())}


def verify_code(peer, value, now):
    valid = peer.expires > now and hmac.compare_digest(peer.code_hash or "", digest(value))
    peer.code_hash = None
    peer.status = "active" if valid else "revoked"
    return valid


def admitted(user_id):
    return request_admitted(user_id, None)["admitted"]


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


def deliver_receipt(token, message_id):
    from storage.service.chat import send_chat_message

    with get_db() as db:
        account = authenticate(db, token)
        receipt = db.get(Inbound, (account.account, message_id))
        if receipt and receipt.enqueue_chat:
            send_chat_message(receipt.enqueue_chat, user_id=account.user_id, role="manager",
                              run_seq=receipt.enqueue_seq)
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
