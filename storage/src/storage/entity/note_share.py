from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class NoteShareEntity(Base, BaseEntity):
    __tablename__ = "note_share"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    share_id = Column(String, nullable=False, unique=True, index=True)
    note_id = Column(String, nullable=False)
    password_hash = Column(String, nullable=True)
    revoked_at = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "note_id"),
    )
