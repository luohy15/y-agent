from sqlalchemy import Column, Integer, String, JSON, ForeignKey, UniqueConstraint, SmallInteger
from .base import Base, BaseEntity


class NoteEntity(Base, BaseEntity):
    __tablename__ = "note"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    note_id = Column(String, nullable=False)
    content_key = Column(String, nullable=False)
    front_matter = Column(JSON, nullable=True)
    deleted_at = Column(String, nullable=True)
    enc_version = Column(SmallInteger, nullable=False, server_default="0", default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "note_id"),
    )
