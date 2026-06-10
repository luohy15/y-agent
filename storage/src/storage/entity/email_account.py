from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class EmailAccountEntity(Base, BaseEntity):
    __tablename__ = "email_account"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    address = Column(String, nullable=False)
    app_password = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "address"),
    )
