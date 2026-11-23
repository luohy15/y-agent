import hmac
import secrets
import time

import httpx
from loguru import logger
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from storage.database.base import get_db
from storage.entity.bot_config import BotConfigEntity as Bot
from storage.entity.relay_credential import RelayCredentialEntity as Relay
from storage.entity.vm_config import VmConfigEntity as Node
from storage.entity.wechat import (
    WechatAccountEntity as Account, WechatBindingEntity as Binding, WechatContextEntity as Context,
    WechatInboundEntity as Inbound, WechatOutboxEntity as Outbox, WechatPeerEntity as Peer,
)
from storage.repository.wechat import bridge_account, digest, locked_account
from storage.service import wechat_provider as provider
from storage.service.user_access import request_admitted, resolve_maintainer

QR_TTL = 480
CODE_TTL = 600
CODE_ATTEMPTS = 5
REFUSAL = "This WeChat account is not bound."
TOKEN_FIELDS = ("bot_token", "bridge_token")
LIVE = ("open", "awaiting_code")
TERMINAL_QR = {
    "expired": "QR expired. Start again.",
    "verify_code_blocked": "WeChat PIN blocked. Start again.",
    "binded_redirect": "ClawBot already bound elsewhere; no credentials reused",
    "unknown": "Unknown WeChat login state",
    "provider_error": "WeChat provider request failed",
}


class ChannelError(Exception):
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


def lock_channel(db):
    db.execute(text("SELECT pg_advisory_xact_lock(4400, 1)"))
    return locked_account(db)


def is_maintainer(user_id):
    maintainer = resolve_maintainer()
    return user_id is not None and maintainer["internal_id"] == user_id


def admitted(user_id):
    return request_admitted(user_id, None)["admitted"]


def binding_view(payload, *, maintainer):
    if maintainer:
        return payload
    return {key: value for key, value in payload.items() if key not in TOKEN_FIELDS}


def judge_code(code_hash, expires, attempts, value, now):
    if not isinstance(code_hash, str) or not isinstance(expires, int) or expires <= now:
        return "expired"
    if not isinstance(attempts, int) or attempts >= CODE_ATTEMPTS:
        return "blocked"
    candidate = digest(value or "")
    if len(code_hash) == len(candidate) and hmac.compare_digest(code_hash, candidate):
        return "ok"
    return "blocked" if attempts + 1 >= CODE_ATTEMPTS else "retry"


def generation_gate(message_id, generation):
    return isinstance(message_id, str) and bool(generation) and message_id.startswith(
        f"msg_evt_wc_{generation}_")


def outbox_ids(key, count):
    return [digest(f"{key}:{index}") for index in range(count)]


def _require_admitted(user_id):
    if not admitted(user_id):
        raise ChannelError(403, "This account is not admitted")


def _require_maintainer(user_id):
    _require_admitted(user_id)
    if not is_maintainer(user_id):
        raise ChannelError(403, "Maintainer only")


def binding_is_live(status, expires, now):
    return status in LIVE and isinstance(expires, int) and expires > now


def live_binding(db, user_id, now=None):
    if now is None:
        now = int(time.time())
    return db.scalar(select(Binding).where(
        Binding.user_id == user_id, Binding.status.in_(LIVE), Binding.expires > now))


def expire_stale_open(db, user_id, now):
    """Drop this caller's expired rows that still occupy wechat_binding_one_live."""
    db.execute(update(Binding).where(
        Binding.user_id == user_id, Binding.status.in_(LIVE), Binding.expires <= now,
    ).values(status="expired", code_hash=None))


def peer_for_user(db, user_id):
    return db.scalar(select(Peer).where(Peer.user_id == user_id))


def peer_key(db, account, peer):
    return db.scalar(select(Peer).where(Peer.account == account, Peer.peer == peer))


def peer_blockers(db, user_id, account):
    missing = []
    if not account or account.status != "active":
        missing.append("No active WeChat bot")
    node = db.scalar(select(Node).where(Node.user_id == user_id, Node.name == "default"))
    if node is None or not node.enabled:
        missing.append("No enabled default node")
    else:
        if not (node.work_dir or "").strip():
            missing.append("Default node has no work directory")
        if not ((node.vm_name or "").strip() or (node.ec2_instance_id or "").strip()):
            missing.append("Default node has no connection")
        if (node.auth_mode or "relay") == "subscription":
            if not (node.api_token or "").strip():
                missing.append("Default node has no credentials")
        elif db.scalar(select(Relay.id).where(Relay.user_id == user_id)) is None:
            missing.append("No relay credential for this user")
    enabled = db.scalar(select(func.count()).select_from(Bot).where(
        Bot.user_id == user_id, Bot.enabled.is_(True)))
    if not enabled:
        missing.append("No enabled bot")
    return missing


def preflight(db, user_id, account):
    _require_admitted(user_id)
    if live_binding(db, user_id):
        raise ChannelError(409, "A binding session is already open")
    if is_maintainer(user_id):
        return
    missing = peer_blockers(db, user_id, account)
    if missing:
        raise ChannelError(409, "; ".join(missing))


def _tokens_match(stored, received):
    if not isinstance(stored, str) or not isinstance(received, str) or len(stored) != len(received):
        return False
    return secrets.compare_digest(stored, received)


def _bases_match(stored, received):
    try:
        return provider.provider_base(stored or "") == provider.provider_base(received or "")
    except ValueError:
        return False


def _binding_for(db, user_id, session_id):
    row = db.scalar(select(Binding).where(
        Binding.binding_id == session_id, Binding.user_id == user_id).with_for_update())
    if not row:
        raise ChannelError(404, "Unknown binding session")
    return row


def _wipe_peer_rows(db, account, peer):
    db.execute(delete(Context).where(Context.account == account, Context.peer == peer))
    db.execute(delete(Outbox).where(Outbox.account == account, Outbox.peer == peer))


def _cancel_live(db, keep=None):
    stmt = update(Binding).where(Binding.status.in_(LIVE))
    if keep:
        stmt = stmt.where(Binding.binding_id != keep)
    db.execute(stmt.values(status="cancelled", code_hash=None))


def stop_account_if_idle(db, account):
    if not account or account.status != "active":
        return
    active = db.scalar(select(func.count()).select_from(Peer).where(
        Peer.account == account.account, Peer.status == "active"))
    waiting = db.scalar(select(func.count()).select_from(Binding).where(
        Binding.account == account.account, Binding.status == "awaiting_code"))
    if active or waiting:
        return
    account.status = "revoked"
    account.bot_token = None
    account.bridge_hash = None


def _replace_account(db, old, user_id, bot_id, token, base, keep):
    secret = secrets.token_urlsafe(40)
    if old:
        _cancel_live(db, keep)
        db.execute(delete(Context).where(Context.account == old.account))
        db.execute(delete(Outbox).where(Outbox.account == old.account))
        db.execute(delete(Inbound).where(Inbound.account == old.account))
        db.execute(delete(Peer).where(Peer.account == old.account))
        db.delete(old)
        db.flush()
    row = Account(slot=1, account=bot_id, user_id=user_id, status="active", bot_token=token,
                  bridge_hash=digest(secret), base_url=base)
    db.add(row)
    db.flush()
    return row, secret


def _rotate_account(account, token, base):
    secret = secrets.token_urlsafe(40)
    account.bot_token = token
    account.base_url = base
    account.bridge_hash = digest(secret)
    account.status = "active"
    return secret


def _fetch_qr():
    try:
        return provider.qr_start()
    except (provider.ProviderError, httpx.HTTPError, ValueError):
        logger.warning("wechat qr start failed")
        raise ChannelError(502, "WeChat provider request failed") from None


def start(user_id):
    with get_db() as db:
        now = int(time.time())
        account = lock_channel(db)
        expire_stale_open(db, user_id, now)
        preflight(db, user_id, account)
    qr = _fetch_qr()
    binding_id = secrets.token_urlsafe(24)
    try:
        with get_db() as db:
            now = int(time.time())
            account = lock_channel(db)
            expire_stale_open(db, user_id, now)
            preflight(db, user_id, account)
            db.add(Binding(binding_id=binding_id, user_id=user_id, qrcode=qr["qrcode"],
                           base_url=qr["base"], attempts=0, expires=now + QR_TTL,
                           status="open"))
            db.flush()
    except IntegrityError:
        raise ChannelError(409, "A binding session is already open") from None
    return {"session_id": binding_id, "qrcode": qr["image"], "status": "open"}


def poll(user_id, session_id, pin=None):
    _require_admitted(user_id)
    with get_db() as db:
        lock_channel(db)
        binding = _binding_for(db, user_id, session_id)
        if binding.status == "awaiting_code":
            return {"status": "awaiting_code", "peer": binding.peer}
        if binding.status != "open":
            return {"status": binding.status}
        if binding.expires <= int(time.time()):
            binding.status = "expired"
            binding.code_hash = None
            stop_account_if_idle(db, locked_account(db))
            return {"status": "expired", "detail": TERMINAL_QR["expired"]}
        qrcode, base = binding.qrcode, binding.base_url
    result = _read_provider_values(qrcode, base, pin)
    with get_db() as db:
        account = lock_channel(db)
        binding = _binding_for(db, user_id, session_id)
        if binding.status != "open":
            return {"status": binding.status, "peer": binding.peer}
        return _apply_qr(db, user_id, account, binding, result)


def _read_provider_values(qrcode, base, pin):
    try:
        return provider.qr_status(qrcode, base, pin)
    except ValueError:
        return {"state": "unknown", "base": base}


def _apply_qr(db, user_id, account, binding, result):
    state = result.get("state")
    if state == "scaned_but_redirect" and result.get("base"):
        binding.base_url = result["base"]
        return {"status": "scaned"}
    if state in {"wait", "scaned", "need_verifycode"}:
        return {"status": state}
    if state == "confirmed":
        return confirm(db, user_id, account, binding, result)
    binding.status = "expired" if state == "expired" else "failed"
    binding.code_hash = None
    stop_account_if_idle(db, account)
    detail = TERMINAL_QR.get(state, TERMINAL_QR["unknown"])
    return {"status": state or "unknown", "detail": detail}


def confirm(db, user_id, account, binding, result):
    bot_id = result.get("account") or ""
    token = result.get("bot_token") or ""
    base = result.get("baseurl") or ""
    sender = result.get("peer") or ""
    if not bot_id or not token or not sender or not base:
        binding.status = "failed"
        return {"status": "rejected", "detail": "Provider confirmation was incomplete"}
    maintainer = is_maintainer(user_id)
    bridge_token = None
    if maintainer:
        if account and account.user_id != user_id:
            binding.status = "failed"
            return {"status": "rejected", "detail": "Not the binding owner"}
        if account and account.account == bot_id:
            if _sender_taken(db, account, sender, user_id, binding.binding_id):
                binding.status = "failed"
                return {"status": "rejected", "detail": "This WeChat account is already bound."}
            bridge_token = _rotate_account(account, token, base)
        else:
            account, bridge_token = _replace_account(
                db, account, user_id, bot_id, token, base, binding.binding_id)
    else:
        same = (account and account.status == "active" and account.account == bot_id
                and _bases_match(account.base_url, base) and _tokens_match(account.bot_token, token))
        if not same:
            binding.status = "cancelled"
            binding.code_hash = None
            return {"status": "rejected",
                    "detail": "Provider returned a different bot. Session cancelled."}
        if _sender_taken(db, account, sender, user_id, binding.binding_id):
            binding.status = "failed"
            binding.code_hash = None
            return {"status": "rejected", "detail": "This WeChat account is already bound."}
    code = f"{secrets.randbelow(1000000):06d}"
    binding.account = account.account
    binding.peer = sender
    binding.code_hash = digest(code)
    binding.attempts = 0
    binding.expires = int(time.time()) + CODE_TTL
    binding.status = "awaiting_code"
    payload = {"status": "confirmed", "code": code, "peer": sender}
    if maintainer:
        payload.update(account=account.account, baseurl=account.base_url, bot_token=token,
                       bridge_token=bridge_token)
    return binding_view(payload, maintainer=maintainer)


def cancel(user_id, session_id):
    _require_admitted(user_id)
    with get_db() as db:
        account = lock_channel(db)
        binding = _binding_for(db, user_id, session_id)
        if binding.status in LIVE:
            binding.status = "cancelled"
            binding.code_hash = None
            stop_account_if_idle(db, account)
        return {"status": binding.status}


def _note(db, account, peer_id, message, now):
    row = peer_key(db, account.account, peer_id)
    if row:
        row.last_error = message
        row.last_error_at = now
    else:
        account.last_error = message


def activate(db, account, binding):
    sender = binding.peer
    current = peer_key(db, account.account, sender)
    if current and current.status == "active" and current.user_id != binding.user_id:
        return False
    owner_row = peer_for_user(db, binding.user_id)
    victims = []
    for row in (current, owner_row):
        if row is not None and row not in victims:
            victims.append(row)
    for row in victims:
        _wipe_peer_rows(db, row.account, row.peer)
        db.delete(row)
    db.flush()
    db.add(Peer(account=account.account, peer=sender, user_id=binding.user_id, status="active",
                generation=secrets.token_hex(16)))
    binding.status = "confirmed"
    binding.code_hash = None
    return True


def _sender_taken(db, account, sender, user_id, binding_id):
    if not account:
        return False
    other = db.scalar(select(Binding.binding_id).where(
        Binding.peer == sender, Binding.status == "awaiting_code", Binding.binding_id != binding_id))
    held = peer_key(db, account.account, sender)
    return bool(other) or bool(held and held.status == "active" and held.user_id != user_id)


def _consume_code(db, account, binding, text, now, peer, message_id):
    verdict = judge_code(binding.code_hash, binding.expires, binding.attempts or 0, text.strip(), now)
    if verdict == "ok":
        if activate(db, account, binding):
            notice = "Binding confirmed."
        else:
            binding.status = "failed"
            binding.code_hash = None
            notice = "This WeChat account is already bound."
    elif verdict == "expired":
        binding.status = "expired"
        binding.code_hash = None
        stop_account_if_idle(db, account)
        notice = "Binding code invalid or expired. Start a new login."
    else:
        binding.attempts = (binding.attempts or 0) + 1
        if verdict == "blocked":
            binding.status = "failed"
            binding.code_hash = None
            stop_account_if_idle(db, account)
        notice = "Binding code invalid or expired. Start a new login."
    enqueue(db, account, peer, notice, digest(f"{binding.binding_id}:{message_id}"), binding.user_id)
    return {"result": "notice"}


def context_for(db, account, peer):
    return db.scalar(select(Context).filter_by(account=account.account, peer=peer))


def _remember_context(db, account, peer, owner, context_token):
    if not context_token:
        return
    context = context_for(db, account, peer)
    if not context:
        context = Context(key=secrets.token_hex(16), account=account.account, peer=peer, user_id=owner)
        db.add(context)
    context.user_id = owner
    context.context_token = context_token
    for row in db.scalars(select(Outbox).filter_by(account=account.account, peer=peer, status="blocked_on_context")):
        row.status = "pending"


async def inbound(db, account, message_id, peer, text, context_token, media):
    from storage.dto.chat import Chat
    from storage.repository import chat as chat_repo
    from storage.service import chat as chats
    from storage.service.reply_route import split_chat_route
    from storage.util import get_utc_iso8601_timestamp

    lock_channel(db)
    if db.get(Inbound, (account.account, message_id)):
        return {"result": "duplicate"}
    now = int(time.time())
    recent = db.scalar(select(func.count()).select_from(Inbound).where(
        Inbound.account == account.account, Inbound.peer == peer,
        Inbound.created_at_unix >= (now - 60) * 1000))
    active = peer_key(db, account.account, peer)
    waiting = db.scalar(select(Binding).where(
        Binding.account == account.account, Binding.peer == peer, Binding.status == "awaiting_code",
    ).with_for_update())
    if waiting:
        owner = waiting.user_id
    elif active and active.status == "active":
        owner = active.user_id
    else:
        owner = account.user_id
    receipt = Inbound(account=account.account, message_id=message_id, peer=peer, user_id=owner)
    db.add(receipt)
    if recent >= 30:
        return {"result": "rate_limited"}
    _remember_context(db, account, peer, owner, context_token)
    if waiting:
        return _consume_code(db, account, waiting, text or "", now, peer, message_id)
    if not active or active.status != "active":
        enqueue(db, account, peer, REFUSAL, digest(f"refuse:{message_id}"), account.user_id)
        return {"result": "notice"}
    if not admitted(active.user_id):
        return {"result": "not_admitted"}
    event = digest(f"{active.generation}:{message_id}")
    if media or not (text or "").strip():
        enqueue(db, account, peer, "Text messages only for now.", event, active.user_id)
        return {"result": "notice"}
    routed_id, routed_body = split_chat_route(text, skip_leading_quotes=True)
    if routed_id:
        target = await chat_repo.get_chat(active.user_id, routed_id)
        if not target:
            notice = f"chat /{routed_id} not found"
        else:
            try:
                accepted = await chats.accept_user_message(
                    active.user_id, target, routed_body, source="wechat", human_reply=True, session=db,
                    event_id=f"wc_{active.generation}_{event}")
                if not accepted.already_running:
                    receipt.enqueue_chat = accepted.chat.id
                    receipt.enqueue_seq = accepted.chat.run_seq
                return {"result": "accepted"}
            except chats.resume_gate.ChatReadOnly:
                notice = "This conversation is read-only. Send /clear to start a new one."
        enqueue(db, account, peer, notice, event, active.user_id)
        return {"result": "notice"}
    reset = text.strip() in {"/clear", "/new"}
    chat = chat_repo.find_latest_chat_by_role(active.user_id, "manager")
    if not chat or reset:
        timestamp = get_utc_iso8601_timestamp()
        chat = Chat(id=chats.new_chat_id(active.user_id), role="manager", messages=[],
                    create_time=timestamp, update_time=timestamp, running=False)
        chat_repo._insert_chat_sync(active.user_id, chat, session=db)
        chat_repo.release_role(active.user_id, "manager", except_chat_id=chat.id, session=db)
    try:
        accepted = await chats.accept_user_message(
            active.user_id, chat, "load manager skill" if reset else text, role="manager",
            source=None if reset else "wechat", human_reply=True, session=db,
            event_id=f"wc_{active.generation}_{event}")
        if not accepted.already_running:
            receipt.enqueue_chat = accepted.chat.id
            receipt.enqueue_seq = accepted.chat.run_seq
        if not reset:
            return {"result": "accepted"}
        notice = "Started a new manager conversation."
    except chats.resume_gate.ChatReadOnly:
        notice = "This conversation is read-only. Send /clear to start a new one."
    enqueue(db, account, peer, notice, event, active.user_id)
    return {"result": "notice"}


async def deliver_receipt(token, message_id):
    from storage.repository import chat as chat_repo
    from storage.service.chat import send_chat_message

    with get_db() as db:
        account = authenticate(db, token)
        receipt = db.get(Inbound, (account.account, message_id))
        if not receipt or not receipt.enqueue_chat or not receipt.user_id:
            return
        chat_id = receipt.enqueue_chat
        run_seq = receipt.enqueue_seq
        user_id = receipt.user_id
        chat = await chat_repo.get_chat(user_id, chat_id)
        send_chat_message(
            chat_id, user_id=user_id, run_seq=run_seq,
            role=getattr(chat, "role", None), skill=getattr(chat, "skill", None),
            trace_id=getattr(chat, "trace_id", None), work_dir=getattr(chat, "work_dir", None),
        )
        receipt.enqueue_chat = None


def enqueue(db, account, peer, body, key, user_id):
    from storage.service.wechat_format import chunks

    parts = chunks(body)
    ids = outbox_ids(key, len(parts))
    if not ids or db.scalar(select(Outbox.seq).filter_by(outbox_id=ids[0])):
        return
    queued = db.scalar(select(func.count()).select_from(Outbox).where(
        Outbox.account == account.account, Outbox.peer == peer,
        Outbox.status.not_in(("sent", "failed"))))
    if queued + len(parts) > 100:
        raise ChannelError(429, "Peer outbox full")
    context = context_for(db, account, peer)
    status = "pending" if context and context.context_token else "blocked_on_context"
    for outbox_id, part in zip(ids, parts, strict=True):
        db.add(Outbox(account=account.account, peer=peer, user_id=user_id, outbox_id=outbox_id,
                      text=part, status=status))


def _own_status(db, user_id, account):
    binding = live_binding(db, user_id)
    peer = peer_for_user(db, user_id)
    if binding:
        payload = {"status": binding.status}
        if binding.peer:
            payload["peer"] = binding.peer
        return payload
    if peer and peer.status == "active" and account and account.status == "active":
        payload = {"status": "active", "peer": peer.peer, "last_error": peer.last_error,
                   "last_error_at": peer.last_error_at}
        payload["outbox"] = dict(db.execute(select(Outbox.status, func.count()).where(
            Outbox.account == account.account, Outbox.peer == peer.peer).group_by(Outbox.status)).all())
        return payload
    if peer:
        return {"status": peer.status, "peer": peer.peer}
    return {"status": "unbound"}


def status(user_id):
    _require_admitted(user_id)
    with get_db() as db:
        account = lock_channel(db)
        payload = _own_status(db, user_id, account)
        if is_maintainer(user_id) and account:
            payload["account_status"] = account.status
            payload["heartbeat"] = account.heartbeat
            payload["last_poll"] = account.last_poll
        return payload


def channel_summary(user_id):
    """Binding inventory for the caller's own peer. No bot token."""
    _require_admitted(user_id)
    now = int(time.time())
    with get_db() as db:
        account = db.scalar(select(Account).limit(1))
        payload = _own_status(db, user_id, account)
        shown = "pending" if payload["status"] in LIVE else payload["status"]
        heartbeat = account.heartbeat if account else None
        last_poll = account.last_poll if account else None
        return {
            "status": shown,
            "account": account.account if account else None,
            "peer": payload.get("peer"),
            "available": bool(
                account and account.status == "active" and bridge_live(heartbeat, now) and shown == "active"),
            "heartbeat_age_seconds": now - heartbeat if isinstance(heartbeat, int) else None,
            "last_poll_age_seconds": now - last_poll if isinstance(last_poll, int) else None,
            "last_error": payload.get("last_error"),
            "outbox": payload.get("outbox") or {},
        }


def owner_state(user_id, action):
    if action == "status":
        return channel_summary(user_id)
    if action == "unbind":
        return unbind(user_id)
    raise ChannelError(404, "Unknown channel action")


def peers(user_id):
    _require_maintainer(user_id)
    with get_db() as db:
        account = lock_channel(db)
        if not account:
            return {"peers": []}
        rows = db.scalars(select(Peer).where(Peer.account == account.account).order_by(Peer.peer))
        return {"peers": [{"account": row.account, "peer": row.peer, "user_id": row.user_id,
                           "status": row.status, "last_error": row.last_error,
                           "last_error_at": row.last_error_at} for row in rows]}


def revoke_peer(db, account, row):
    _wipe_peer_rows(db, row.account, row.peer)
    row.status = "revoked"
    row.code_hash = None
    db.execute(update(Binding).where(
        Binding.account == account.account, Binding.peer == row.peer, Binding.status.in_(LIVE),
    ).values(status="cancelled", code_hash=None))
    stop_account_if_idle(db, account)


def unbind(user_id):
    _require_admitted(user_id)
    with get_db() as db:
        account = lock_channel(db)
        row = peer_for_user(db, user_id)
        if not account or not row or row.status != "active":
            return {"status": "unbound"}
        revoke_peer(db, account, row)
        return {"status": "revoked"}


def revoke(user_id, peer):
    _require_maintainer(user_id)
    with get_db() as db:
        account = lock_channel(db)
        if not account:
            raise ChannelError(404, "Unknown peer")
        row = peer_key(db, account.account, peer)
        if not row:
            raise ChannelError(404, "Unknown peer")
        if row.status == "active":
            revoke_peer(db, account, row)
        return {"status": row.status, "peer": row.peer, "user_id": row.user_id}


def send(user_id, body):
    _require_admitted(user_id)
    with get_db() as db:
        account = lock_channel(db)
        if not account or account.status != "active":
            raise ChannelError(409, "No active bot")
        row = peer_for_user(db, user_id)
        if not row or row.status != "active":
            raise ChannelError(409, "No active binding")
        enqueue(db, account, row.peer, body, secrets.token_hex(16), row.user_id)
        return {"ok": True}


WECHAT_BRIDGE_STALE_SECONDS = 300


def bridge_live(heartbeat, now):
    if isinstance(heartbeat, bool) or not isinstance(heartbeat, int):
        return False
    age = now - heartbeat
    return 0 <= age < WECHAT_BRIDGE_STALE_SECONDS


def _notify_target(db, user_id, now, *, lock=True):
    account = lock_channel(db) if lock else db.scalar(select(Account).limit(1))
    if not account or account.status != "active" or not bridge_live(account.heartbeat, now):
        return None
    row = peer_for_user(db, user_id)
    if not row or row.status != "active":
        return None
    return account, row


def notify_available(user_id):
    try:
        with get_db() as db:
            return _notify_target(db, user_id, int(time.time()), lock=False) is not None
    except Exception:
        logger.exception("wechat notify availability failed user_id={}", user_id)
        return False


def notify_user(user_id, text):
    """Queue a proactive text for this user's peer. No maintainer gate. Never raises."""
    if not isinstance(text, str) or not text.strip():
        return False
    now = int(time.time())
    try:
        with get_db() as db:
            target = _notify_target(db, user_id, now)
            if not target:
                return False
            account, row = target
            enqueue(db, account, row.peer, text, secrets.token_hex(16), row.user_id)
        return True
    except ChannelError:
        return False
    except Exception:
        logger.exception("wechat notify failed user_id={}", user_id)
        return False


def authenticate(db, token):
    lock_channel(db)
    row = bridge_account(db, token)
    if not row:
        raise ChannelError(401, "Invalid bridge token")
    return row


def enqueue_reply(chat, user_id):
    if getattr(chat, "role", None) != "manager":
        return
    reply = None
    trigger = None
    for message in reversed(getattr(chat, "messages", None) or []):
        if message.role == "user":
            trigger = message
            break
        if not reply and message.role == "assistant" and isinstance(message.content, str) and message.content.strip():
            reply = message
    else:
        return
    if not reply or trigger is None or trigger.source != "wechat" or not trigger.id:
        return
    with get_db() as db:
        account = lock_channel(db)
        if not account or account.status != "active":
            return
        for row in db.scalars(select(Peer).where(Peer.user_id == user_id, Peer.status == "active")):
            if generation_gate(trigger.id, row.generation):
                enqueue(db, account, row.peer, reply.content, f"{chat.id}:{reply.id}:{trigger.id}", row.user_id)
                return


def claim(db, account):
    now = int(time.time())
    rows = db.scalars(select(Outbox).where(
        Outbox.account == account.account, Outbox.status.in_(("pending", "leased"))).order_by(Outbox.seq))
    waiting = set()
    for row in rows:
        if row.peer in waiting:
            continue
        if not admitted(row.user_id):
            row.status = "failed"
            _note(db, account, row.peer, "admission_revoked", now)
            continue
        if row.available > now:
            waiting.add(row.peer)
            continue
        if row.attempts >= 5:
            row.status = "failed"
            _note(db, account, row.peer, "lease_attempts_exhausted", now)
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
    now = int(time.time())
    finish(row, ok, now)
    if not ok:
        _note(db, account, row.peer, "send_attempts_exhausted" if row.status == "failed" else "send_rejected", now)
    return {"ok": True}
