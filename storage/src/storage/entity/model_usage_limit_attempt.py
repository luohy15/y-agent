from sqlalchemy import (
    CheckConstraint,
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


class ModelUsageLimitAttemptEntity(Base, BaseEntity):
    """One subscription limit-window refresh attempt (todo 3717).

    A row exists for every attempt that actually ran, success or failure.
    Lock-skipped calls are not attempts. Local wall-clock date/hour match
    model_usage_hourly so a bounded read can line the two up. attempted_at
    is collection time and is never a substitute for a source observed_at.
    """

    __tablename__ = "model_usage_limit_attempt"

    id = Column(Integer, primary_key=True, autoincrement=True)
    attempt_id = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    attempted_at = Column(String, nullable=False)
    attempt_date = Column(Date, nullable=False)
    attempt_hour = Column(SmallInteger, nullable=False)  # 0-23 local wall-clock hour
    trigger = Column(String, nullable=False)  # scheduled | manual
    status = Column(String, nullable=False)  # ok | failed
    error = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("attempt_id", name="uq_model_usage_limit_attempt_id"),
        CheckConstraint("attempt_hour >= 0 AND attempt_hour <= 23", name="ck_model_usage_limit_attempt_hour"),
        CheckConstraint("trigger IN ('scheduled', 'manual')", name="ck_model_usage_limit_attempt_trigger"),
        CheckConstraint("status IN ('ok', 'failed')", name="ck_model_usage_limit_attempt_status"),
        Index("ix_model_usage_limit_attempt_user_date", "user_id", "attempt_date"),
    )
