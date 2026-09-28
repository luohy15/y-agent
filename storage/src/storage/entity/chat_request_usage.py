from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, UniqueConstraint

from .base import Base, BaseEntity


class ChatRequestUsageEntity(Base, BaseEntity):
    """One attributed Claude Code request, uploaded from a VM transcript.

    A row exists only when the scanner positively attributed the request to one
    of the owner's chats, so chat_id is never NULL and there is no read-time
    external_id join. A counter is NULL when the transcript omitted its key and
    0 when the key was present as 0. usage_state is `missing` when the record
    had no usable usage dict and `observed` otherwise.
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
    usage_state = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_chat_request_usage"),
        CheckConstraint(
            "usage_state IN ('observed', 'missing')",
            name="ck_chat_request_usage_state",
        ),
        Index("ix_chat_request_usage_user_chat", "user_id", "chat_id"),
    )
