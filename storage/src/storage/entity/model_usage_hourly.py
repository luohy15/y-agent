from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)

from .base import Base, BaseEntity


class ModelUsageHourlyEntity(Base, BaseEntity):
    """Provider-generic per-hour LLM token/cost usage.

    Mirrors `model_usage_daily` at hour grain. One row per
    (user, date, hour, source, scope_id, model); local wall-clock
    (DATE + hour 0-23) so SUM(hourly WHERE usage_date=d) compares
    directly to the daily row for d (todo 3165).
    """

    __tablename__ = "model_usage_hourly"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    usage_date = Column(Date, nullable=False)
    usage_hour = Column(SmallInteger, nullable=False)  # 0-23 local wall-clock hour
    # --- generic dimensions ---
    source = Column(String, nullable=False)              # 'crs' (the spend pipe)
    provider = Column(String, nullable=False, default="")  # model vendor: 'anthropic'|'openai'|... ('' if unknown)
    model = Column(String, nullable=False, default="*")     # specific model id; '*' = all-models aggregate
    scope = Column(String, nullable=False, default="aggregate")  # 'account' | 'aggregate'
    scope_id = Column(String, nullable=False, default="")  # CRS accountId; '' for source-level aggregate
    scope_name = Column(String, nullable=False, default="")  # human label
    # --- token counters (0 when a source can't provide them) ---
    input_tokens = Column(BigInteger, nullable=False, default=0)
    output_tokens = Column(BigInteger, nullable=False, default=0)
    cache_create_tokens = Column(BigInteger, nullable=False, default=0)
    cache_read_tokens = Column(BigInteger, nullable=False, default=0)
    all_tokens = Column(BigInteger, nullable=False, default=0)
    requests = Column(BigInteger, nullable=False, default=0)
    # --- cost ---
    cost = Column(Float, nullable=False, default=0.0)       # USD
    cost_basis = Column(String, nullable=False, default="real")  # 'real' | 'rated' | 'notional'
    synced_at = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "usage_date", "usage_hour", "source", "scope_id", "model",
            name="uq_model_usage_hourly",
        ),
        Index("ix_model_usage_hourly_user_date", "user_id", "usage_date"),
        Index("ix_model_usage_hourly_source_date", "source", "usage_date"),
    )
