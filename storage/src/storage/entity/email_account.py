from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint, SmallInteger
from .base import Base, BaseEntity


class EmailAccountEntity(Base, BaseEntity):
    __tablename__ = "email_account"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    address = Column(String, nullable=False)
    app_password = Column(String, nullable=False)
    address_bidx = Column(String, nullable=True)
    enc_version = Column(SmallInteger, nullable=False, server_default="0", default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "address"),
    )
