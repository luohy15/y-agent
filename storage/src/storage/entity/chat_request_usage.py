from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, UniqueConstraint

from .base import Base, BaseEntity


class ChatRequestUsageEntity(Base, BaseEntity):
    """One attributed Claude Code request, uploaded from a VM transcript.

    A row exists only when the scanner positively attributed the request to one
    of the owner's chats, so chat_id is never NULL and there is no read-time
    external_id join. A counter is NULL when the transcript omitted its key and
    0 when the key was present as 0. usage_state is `missing` when the record
    had no usable usage dict and `observed` otherwise.

    Codex and agy rows store the turn delta in the four counters. The nullable
    cumulative_* columns are that turn's thread total, the anchor for the next
    delta. A NULL cumulative column is a legacy snapshot: the counters themselves
    are the anchor.

    `backend` names the agent backend that produced the turn. Claude Code
    transcript uploads stamp 'claude_code'; the worker stamps 'codex' / 'agy'.
    A NULL is a row written before the column existed, not a different kind of
    row. The non-relay usage source selects on it (todo 4463).
    """

    __tablename__ = "chat_request_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    request_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    chat_id = Column(String, nullable=False)
    model = Column(String, nullable=False)
    requested_at = Column(String, nullable=False)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    cache_creation_tokens = Column(Integer, nullable=True)
    cache_read_tokens = Column(Integer, nullable=True)
    cumulative_input_tokens = Column(Integer, nullable=True)
    cumulative_output_tokens = Column(Integer, nullable=True)
    cumulative_cache_creation_tokens = Column(Integer, nullable=True)
    cumulative_cache_read_tokens = Column(Integer, nullable=True)
    usage_state = Column(String, nullable=False)
    applied_effort = Column(String, nullable=True)
    backend = Column(String(32), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_chat_request_usage"),
        CheckConstraint(
            "usage_state IN ('observed', 'missing')",
            name="ck_chat_request_usage_state",
        ),
        CheckConstraint(
            "applied_effort IS NULL OR applied_effort IN ('low', 'medium', 'high', 'xhigh', 'max')",
            name="ck_chat_request_usage_applied_effort",
        ),
        Index("ix_chat_request_usage_user_chat", "user_id", "chat_id"),
        Index("ix_chat_request_usage_user_backend_at", "user_id", "backend", "requested_at"),
    )
