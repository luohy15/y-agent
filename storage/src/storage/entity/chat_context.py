from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from .base import Base, BaseEntity


_JSON = JSON().with_variant(JSONB, "postgresql")


class ChatContextSessionEntity(Base, BaseEntity):
    """One analysed transcript session for one of the owner's chats (todo 3844).

    The upload unit: the VM analyses a transcript and uploads the requests it
    attributed to this chat. Re-analysis replaces the unit's request and
    contributor rows as a whole. The summary columns are computed by the
    server from the uploaded counters and outlive the 30-day detail rows. A
    prompt-size column is NULL when no request had all three input counters.
    """

    __tablename__ = "chat_context_session"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    analyzer_version = Column(Integer, nullable=False)
    token_method = Column(String, nullable=False)
    state = Column(String, nullable=False)
    cli_versions = Column(_JSON, nullable=False)
    gaps = Column(_JSON, nullable=False)
    events = Column(_JSON, nullable=False)
    suggestions = Column(_JSON, nullable=False)
    requests = Column(Integer, nullable=False)
    requests_with_prompt = Column(Integer, nullable=False)
    startup_prompt_tokens = Column(BigInteger, nullable=True)
    peak_prompt_tokens = Column(BigInteger, nullable=True)
    latest_prompt_tokens = Column(BigInteger, nullable=True)
    cumulative_input_tokens = Column(BigInteger, nullable=True)
    cumulative_cache_read_tokens = Column(BigInteger, nullable=True)
    requests_omitted = Column(Integer, nullable=False)
    contributors_omitted = Column(Integer, nullable=False)
    labels_dropped = Column(Integer, nullable=False)
    started_at = Column(String, nullable=True)
    analyzed_at = Column(String, nullable=False)
    analyzed_at_unix = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "chat_id", "session_id", name="uq_chat_context_session"),
        CheckConstraint(
            "state IN ('analyzed', 'partial', 'unsupported')",
            name="ck_chat_context_session_state",
        ),
        Index("ix_chat_context_session_user_analyzed", "user_id", "analyzed_at_unix"),
    )


class ChatContextRequestEntity(Base, BaseEntity):
    """One analysed request: observed counters plus estimated category sizes.

    A counter is NULL when the transcript omitted it and 0 when it was 0.
    `categories` maps each category to bytes / estimated_tokens (NULL is
    unknown) and whether its evidence was complete. Kept 30 days.
    """

    __tablename__ = "chat_context_request"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    request_id = Column(String, nullable=False)
    sequence = Column(Integer, nullable=False)
    epoch = Column(Integer, nullable=False)
    model = Column(String, nullable=False)
    requested_at = Column(String, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    cache_creation_tokens = Column(Integer, nullable=True)
    cache_read_tokens = Column(Integer, nullable=True)
    categories = Column(_JSON, nullable=False)
    unknown_overhead = Column(_JSON, nullable=False)
    gaps = Column(_JSON, nullable=False)
    state = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_chat_context_request"),
        CheckConstraint(
            "state IN ('analyzed', 'partial')",
            name="ck_chat_context_request_state",
        ),
        Index("ix_chat_context_request_unit", "user_id", "chat_id", "session_id", "sequence"),
    )


class ChatContextContributorEntity(Base, BaseEntity):
    """One bounded top contributor of a unit: sizes, digest, safe label only."""

    __tablename__ = "chat_context_contributor"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    occurrence_id = Column(String, nullable=False)
    category = Column(String, nullable=False)
    origin = Column(String, nullable=False)
    label = Column(String, nullable=True)
    digest = Column(String, nullable=True)
    bytes = Column(Integer, nullable=False)
    introduced_request = Column(Integer, nullable=False)
    exposure_requests = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "chat_id", "session_id", "occurrence_id",
            name="uq_chat_context_contributor",
        ),
    )
