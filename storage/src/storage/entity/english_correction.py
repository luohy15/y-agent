from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from .base import Base, BaseEntity


class EnglishCorrectionEntity(Base, BaseEntity):
    __tablename__ = "english_correction"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    correction_id = Column(String, nullable=False)

    chat_id = Column(String, nullable=False)
    message_id = Column(String, nullable=False)
    message_at = Column(String, nullable=False)
    message_at_unix = Column(BigInteger, nullable=False)

    original_text = Column(Text, nullable=False)
    corrected_text = Column(Text, nullable=False)
    error_categories = Column(JSON, nullable=False)
    explanation = Column(Text, nullable=False)
    dismissed = Column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        UniqueConstraint("user_id", "correction_id"),
        UniqueConstraint("user_id", "chat_id", "message_id"),
        Index("ix_english_correction_user_dismissed_msg", "user_id", "dismissed", "message_at_unix"),
    )
