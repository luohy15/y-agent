from sqlalchemy import Column, Integer, String, Text, BigInteger, ForeignKey, UniqueConstraint, JSON, SmallInteger
from .base import Base, BaseEntity


class EmailEntity(Base, BaseEntity):
    __tablename__ = "email"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    email_id = Column(String, nullable=False)
    external_id = Column(String, nullable=True)
    subject = Column(String, nullable=True)
    from_addr = Column(String, nullable=False)
    to_addrs = Column(JSON, nullable=False)
    cc_addrs = Column(JSON, nullable=True)
    bcc_addrs = Column(JSON, nullable=True)
    date = Column(BigInteger, nullable=False, index=True)
    content = Column(Text, nullable=True)
    thread_id = Column(String, nullable=True, index=True)
    account = Column(String, nullable=True, index=True)
    from_addr_bidx = Column(String, nullable=True)
    account_bidx = Column(String, nullable=True)
    enc_version = Column(SmallInteger, nullable=False, server_default="0", default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "email_id"),
        UniqueConstraint("user_id", "account", "external_id"),
    )
