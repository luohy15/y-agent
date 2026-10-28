from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, UniqueConstraint, JSON

from .base import Base, BaseEntity


class ChatLaunchEntity(Base, BaseEntity):
    """One Claude Code spawn. Rows are inserted and never updated.

    A Lambda tail handoff is not a launch. ``launch_effort`` NULL means the
    argv had no ``--effort`` flag and must not be read as a level.
    ``capability`` is ``declared`` when the flag was passed and ``not_required``
    when it was not.
    """

    __tablename__ = "chat_launch"

    id = Column(Integer, primary_key=True, autoincrement=True)
    launch_id = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    chat_id = Column(String, nullable=False)
    trace_id = Column(String, nullable=True)
    run_seq = Column(Integer, nullable=True)
    launched_at = Column(String, nullable=False)
    bot_name = Column(String, nullable=True)
    backend = Column(String, nullable=True)
    model = Column(String, nullable=True)
    requested_effort = Column(String, nullable=True)
    launch_effort = Column(String, nullable=True)
    capability = Column(String, nullable=False)
    input_message_ids = Column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("launch_id", name="uq_chat_launch_launch_id"),
        CheckConstraint(
            "capability IN ('declared', 'not_required')",
            name="ck_chat_launch_capability",
        ),
        CheckConstraint(
            "requested_effort IS NULL OR requested_effort IN ('low', 'medium', 'high', 'xhigh', 'max')",
            name="ck_chat_launch_requested",
        ),
        CheckConstraint(
            "launch_effort IS NULL OR launch_effort IN ('low', 'medium', 'high', 'xhigh', 'max')",
            name="ck_chat_launch_launch",
        ),
        Index("ix_chat_launch_user_chat_launched", "user_id", "chat_id", "launched_at"),
    )
