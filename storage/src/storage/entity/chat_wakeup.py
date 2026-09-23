from sqlalchemy import (
    Boolean, BigInteger, CheckConstraint, Column, ForeignKey, Index, Integer, String,
    Text, UniqueConstraint, text
)
from .base import Base, BaseEntity


class ChatWakeupEntity(Base, BaseEntity):
    """Durable server-side wakeup: fires an ordinary dispatch into a chat at
    ``due_at_unix``, and is watchdog liveness evidence on its trace until then
    (todo 3655). Delivery reuses the todo 3493 outbox pattern: ``pending`` ->
    ``accepted`` (message appended, broker send still possibly owed) ->
    ``delivered``. ``cancelled`` is only reachable from ``pending``.
    """

    __tablename__ = "chat_wakeup"

    id = Column(Integer, primary_key=True, autoincrement=True)
    wakeup_id = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    chat_id = Column(String, nullable=False)
    trace_id = Column(String, nullable=False)
    from_chat_id = Column(String, nullable=True)
    from_topic = Column(String, nullable=True)
    message = Column(Text, nullable=False)
    due_at_unix = Column(BigInteger, nullable=False)

    status = Column(String, nullable=False, default="pending")
    enqueue_needed = Column(Boolean, nullable=True)
    delivery_attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "wakeup_id", name="uq_chat_wakeup_id"),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'delivered', 'cancelled')",
            name="ck_chat_wakeup_status",
        ),
        CheckConstraint("delivery_attempts >= 0", name="ck_chat_wakeup_attempts"),
        Index("ix_chat_wakeup_trace", "user_id", "trace_id", "status"),
        # The watchdog evidence pass and the delivery pass both scan exactly
        # this predicate; declared here so a database built from init_tables
        # has the same shape as the SQL.
        Index("ix_chat_wakeup_due", "due_at_unix",
              postgresql_where=text("status IN ('pending', 'accepted')")),
    )
