from sqlalchemy import Column, Integer, String, Text, JSON, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class NoteEntity(Base, BaseEntity):
    __tablename__ = "note"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    note_id = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    front_matter = Column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "note_id"),
    )
