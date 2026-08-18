from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from .base import Base


class ApiLatencyRollupEntity(Base):
    """Mergeable latency distribution at hour or day grain."""

    __tablename__ = "api_latency_rollup"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    grain = Column(String(4), nullable=False)
    bucket_start = Column(DateTime(timezone=True), nullable=False)
    method = Column(String(8), nullable=False)
    route = Column(String(512), nullable=False)
    status_class = Column(String(3), nullable=False)
    completion = Column(String(16), nullable=False)
    module_slug = Column(String, nullable=False, default="")
    request_count = Column(BigInteger, nullable=False)
    error_count = Column(BigInteger, nullable=False)
    duration_sum_ms = Column(Float, nullable=False)
    duration_min_ms = Column(Float, nullable=False)
    duration_max_ms = Column(Float, nullable=False)
    histogram = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    hist_version = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "grain",
            "bucket_start",
            "method",
            "route",
            "status_class",
            "completion",
            "module_slug",
            name="uq_api_latency_rollup_bucket_dimensions",
        ),
        Index("ix_api_latency_rollup_grain_bucket", "grain", "bucket_start"),
        Index("ix_api_latency_rollup_route_bucket", "route", "bucket_start"),
    )
