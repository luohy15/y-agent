from sqlalchemy import Column, Date, ForeignKey, Index, Integer, String, UniqueConstraint

from .base import Base, BaseEntity


class ChatModelActivityEntity(Base, BaseEntity):
    """Per-chat, per-day assistant model activity derived from chat messages."""

    __tablename__ = "chat_model_activity"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id = Column(String, nullable=False)
    usage_date = Column(Date, nullable=False)
    model = Column(String, nullable=False)
    turns = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "chat_id",
            "usage_date",
            "model",
            name="uq_chat_model_activity",
        ),
        Index("ix_chat_model_activity_user_date_model", "user_id", "usage_date", "model"),
    )
