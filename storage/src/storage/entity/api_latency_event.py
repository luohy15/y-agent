from sqlalchemy import BigInteger, Column, DateTime, Float, Index, String

from .base import Base


class ApiLatencyEventEntity(Base):
    """Lean privacy-safe record for one inbound API attempt."""

    __tablename__ = "api_latency_event"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    duration_ms = Column(Float, nullable=False)
    method = Column(String(8), nullable=False)
    route = Column(String(512), nullable=False)
    status_class = Column(String(3), nullable=False)
    completion = Column(String(16), nullable=False)
    module_slug = Column(String, nullable=False, default="")

    __table_args__ = (
        Index("ix_api_latency_event_started_at", "started_at"),
        Index("ix_api_latency_event_route_started", "route", "started_at"),
    )
