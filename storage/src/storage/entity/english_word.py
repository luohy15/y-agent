from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from .base import Base, BaseEntity


class EnglishWordEntity(Base, BaseEntity):
    __tablename__ = "english_word"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    word_id = Column(String, nullable=False)

    word = Column(String, nullable=False)
    rank = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="unseen", server_default=text("'unseen'"))
    marked_at = Column(String, nullable=True)
    marked_at_unix = Column(BigInteger, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "word"),
        UniqueConstraint("user_id", "word_id"),
        Index("ix_english_word_user_status_rank", "user_id", "status", "rank"),
    )
