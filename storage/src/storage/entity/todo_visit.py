from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class TodoVisitEntity(Base, BaseEntity):
    __tablename__ = "todo_visit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    share_id = Column(String, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("user_id", "share_id", name="uq_todo_visit_user_share"),
    )
