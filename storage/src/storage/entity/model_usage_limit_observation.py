from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from .base import Base, BaseEntity


class ModelUsageLimitObservationEntity(Base, BaseEntity):
    """One window (or one provider-level miss) inside a refresh attempt.

    Rows belong to an attempt and die with it. window_key is empty for a
    provider-level row (error, no windows, or an expected backend absent
    from the envelope). used_percent stays NULL when the source did not
    report a finite number. plan and limit_reached are account-wide signals
    copied onto every row of that account for the attempt; they are not
    per-window facts. observed_at is the source time and may be NULL.
    """

    __tablename__ = "model_usage_limit_observation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    attempt_id = Column(
        String,
        ForeignKey("model_usage_limit_attempt.attempt_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    # Denormalized from the attempt so a bounded range count does not have to
    # join first. Same local wall clock as the attempt row.
    attempt_date = Column(Date, nullable=False)
    backend = Column(String, nullable=False, default="")
    provider = Column(String, nullable=False, default="")
    source = Column(String, nullable=False, default="")
    account_key = Column(String, nullable=False, default="")
    account_name = Column(String, nullable=True)
    state = Column(String, nullable=False)
    error = Column(String, nullable=True)
    observed_at = Column(DateTime(timezone=True), nullable=True)
    window_key = Column(String, nullable=False, default="")
    used_percent = Column(Float, nullable=True)
    reset_at = Column(DateTime(timezone=True), nullable=True)
    plan = Column(String, nullable=True)
    limit_reached = Column(Boolean, nullable=True)
    extra = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "attempt_id", "backend", "account_key", "window_key",
            name="uq_model_usage_limit_observation",
        ),
        CheckConstraint(
            "state IN ('available', 'unavailable', 'reauth_required', 'missing')",
            name="ck_model_usage_limit_observation_state",
        ),
        Index("ix_model_usage_limit_observation_user_date", "user_id", "attempt_date"),
        Index("ix_model_usage_limit_observation_attempt", "attempt_id"),
        Index("ix_model_usage_limit_observation_backend_observed", "user_id", "backend", "observed_at"),
    )
