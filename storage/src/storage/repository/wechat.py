"""Channel writes serialize on the singleton bot row and advisory lock 4400,1."""

import hashlib
import hmac

from sqlalchemy import select

from storage.entity.wechat import WechatAccountEntity


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def locked_account(db):
    return db.scalar(select(WechatAccountEntity).with_for_update())


def bridge_account(db, token):
    if not token or len(token) > 128:
        return None
    fingerprint = digest(token)
    row = db.scalar(select(WechatAccountEntity).where(
        WechatAccountEntity.bridge_hash == fingerprint,
        WechatAccountEntity.status == "active",
    ).with_for_update())
    return row if row and hmac.compare_digest(row.bridge_hash, fingerprint) else None
