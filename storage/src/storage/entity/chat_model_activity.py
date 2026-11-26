from sqlalchemy import (
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)

from .base import Base, BaseEntity


class ChatModelActivityEntity(Base, BaseEntity):
    """Per-chat, per-day, per-hour assistant model activity from chat messages.

    `turns` counts answered prompt groups; `requests` counts attributed
    assistant messages (todo 4483). One attributed assistant message is one
    observed agy Request, so Requests >= Turns structurally.
    """

    __tablename__ = "chat_model_activity"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id = Column(String, nullable=False)
    usage_date = Column(Date, nullable=False)
    usage_hour = Column(SmallInteger, nullable=False, default=0)  # 0-23 local wall-clock hour
    model = Column(String, nullable=False)
    turns = Column(Integer, nullable=False, default=0)
    requests = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "chat_id",
            "usage_date",
            "usage_hour",
            "model",
            name="uq_chat_model_activity",
        ),
        Index("ix_chat_model_activity_user_date_model", "user_id", "usage_date", "model"),
    )
