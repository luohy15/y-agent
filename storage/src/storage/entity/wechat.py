from sqlalchemy import BigInteger, Column, ForeignKey, Index, Integer, SmallInteger, String, Text, UniqueConstraint, text

from storage.entity.base import Base, BaseEntity


class WechatAccountEntity(Base, BaseEntity):
    __tablename__ = "wechat_account"
    account = Column(String, primary_key=True)
    # Retained from the singleton-slot design; unused and nullable.
    slot = Column(Integer)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    bot_token = Column(Text)
    bridge_hash = Column(String)
    base_url = Column(String)
    status = Column(String, nullable=False)
    heartbeat = Column(BigInteger)
    last_poll = Column(BigInteger)
    last_error = Column(String)
    enc_version = Column(SmallInteger, nullable=False, server_default="0")


class WechatPeerEntity(Base, BaseEntity):
    __tablename__ = "wechat_peer"
    account = Column(String, ForeignKey("wechat_account.account", ondelete="CASCADE"), primary_key=True)
    peer = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), unique=True, nullable=False)
    status = Column(String, nullable=False)
    code_hash = Column(String)
    expires = Column(BigInteger)
    generation = Column(String, nullable=False)
    last_error = Column(String)
    last_error_at = Column(BigInteger)


class WechatBindingEntity(Base, BaseEntity):
    __tablename__ = "wechat_binding"
    binding_id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    account = Column(String)
    qrcode = Column(String, nullable=False)
    base_url = Column(String, nullable=False)
    peer = Column(String)
    code_hash = Column(String)
    attempts = Column(Integer, nullable=False, default=0)
    expires = Column(BigInteger, nullable=False)
    status = Column(String, nullable=False)
    __table_args__ = (
        Index("wechat_binding_one_live", "user_id", unique=True,
              postgresql_where=text("status IN ('open', 'awaiting_code')")),
        Index("ix_wechat_binding_awaiting", "account", "peer",
              postgresql_where=text("status = 'awaiting_code'")),
    )


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
    provider_message_id = Column(String)


# Defined outside the class body: `text` there resolves to the class's own column.
Index("ix_wechat_outbox_provider_msg", WechatOutboxEntity.__table__.c.account,
      WechatOutboxEntity.__table__.c.peer, WechatOutboxEntity.__table__.c.provider_message_id,
      postgresql_where=text("provider_message_id IS NOT NULL"))


class WechatInboundEntity(Base, BaseEntity):
    __tablename__ = "wechat_inbound"
    account = Column(String, ForeignKey("wechat_account.account", ondelete="CASCADE"), primary_key=True)
    message_id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=False)
    enqueue_chat = Column(String)
    enqueue_seq = Column(Integer)
    peer = Column(String, nullable=False, index=True)
    quote_text = Column(Text)
    media_kind = Column(String)
    media_name = Column(String)
    enc_version = Column(SmallInteger, nullable=False, server_default="0")
