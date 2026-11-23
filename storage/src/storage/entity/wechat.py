from sqlalchemy import BigInteger, CheckConstraint, Column, ForeignKey, Integer, SmallInteger, String, Text, UniqueConstraint

from storage.entity.base import Base, BaseEntity


class WechatAccountEntity(Base, BaseEntity):
    __tablename__ = "wechat_account"
    slot = Column(Integer, primary_key=True, autoincrement=False)
    account = Column(String, nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    bot_token = Column(Text)
    bridge_hash = Column(String)
    status = Column(String, nullable=False)
    heartbeat = Column(BigInteger)
    last_poll = Column(BigInteger)
    last_error = Column(String)
    enc_version = Column(SmallInteger, nullable=False, server_default="0")
    __table_args__ = (CheckConstraint("slot = 1"),)


class WechatPeerEntity(Base, BaseEntity):
    __tablename__ = "wechat_peer"
    account = Column(String, ForeignKey("wechat_account.account", ondelete="CASCADE"), primary_key=True)
    peer = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("user.id"), unique=True, nullable=False)
    status = Column(String, nullable=False)
    code_hash = Column(String)
    expires = Column(BigInteger)
    generation = Column(String, nullable=False)


class WechatContextEntity(Base, BaseEntity):
    __tablename__ = "wechat_context"
    key = Column(String, primary_key=True)
    account = Column(String, ForeignKey("wechat_account.account", ondelete="CASCADE"), nullable=False)
    peer = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    context_token = Column(Text)
    enc_version = Column(SmallInteger, nullable=False, server_default="0")
    __table_args__ = (UniqueConstraint("account", "peer"),)


class WechatOutboxEntity(Base, BaseEntity):
    __tablename__ = "wechat_outbox"
    seq = Column(BigInteger, primary_key=True)
    outbox_id = Column(String, unique=True, nullable=False)
    account = Column(String, ForeignKey("wechat_account.account", ondelete="CASCADE"), nullable=False)
    peer = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    text = Column(Text, nullable=False)
    status = Column(String, nullable=False, index=True)
    attempts = Column(Integer, nullable=False, default=0)
    available = Column(BigInteger, nullable=False, default=0)
    lease = Column(String)
    enc_version = Column(SmallInteger, nullable=False, server_default="0")


class WechatInboundEntity(Base, BaseEntity):
    __tablename__ = "wechat_inbound"
    account = Column(String, ForeignKey("wechat_account.account", ondelete="CASCADE"), primary_key=True)
    message_id = Column(String, primary_key=True)
    enqueue_chat = Column(String)
    enqueue_seq = Column(Integer)
    peer = Column(String, nullable=False, index=True)
