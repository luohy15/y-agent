from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint, JSON
from .base import Base, BaseEntity


class DevWorktreeEntity(Base, BaseEntity):
    __tablename__ = "dev_worktree"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    worktree_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    project_path = Column(String, nullable=False)
    worktree_path = Column(String, nullable=False)
    branch = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    chat_ids = Column(JSON, nullable=True)
    history = Column(JSON, nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint("user_id", "name"),
    )
