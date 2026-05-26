from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String, Text, UniqueConstraint

from .base import Base, BaseEntity


class UserCookiesEntity(Base, BaseEntity):
    __tablename__ = "user_cookies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    domain = Column(String(128), nullable=False)
    cookies_txt = Column(Text, nullable=False)
    expires_at_unix = Column(BigInteger, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "domain"),
    )
