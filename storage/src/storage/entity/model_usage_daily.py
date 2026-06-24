from sqlalchemy import BigInteger, Column, Date, Float, ForeignKey, Index, Integer, String, UniqueConstraint

from .base import Base, BaseEntity


class ModelUsageDailyEntity(Base, BaseEntity):
    """Provider-generic per-day LLM token/cost usage.

    Modeled on `finance_price` (idempotent daily-keyed upsert). One row per
    (user, date, source, scope_id, model); aggregate sentinels model='*' /
    scope='aggregate' let a source write one row or many under the same key.
    """

    __tablename__ = "model_usage_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    usage_date = Column(Date, nullable=False)
    # --- generic dimensions ---
    source = Column(String, nullable=False)              # 'crs' | 'openrouter' (the spend pipe)
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
    cost_basis = Column(String, nullable=False, default="real")  # 'real' | 'rated'
    synced_at = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "usage_date", "source", "scope_id", "model", name="uq_model_usage_daily"),
        Index("ix_model_usage_daily_user_date", "user_id", "usage_date"),
        Index("ix_model_usage_daily_source_date", "source", "usage_date"),
    )
