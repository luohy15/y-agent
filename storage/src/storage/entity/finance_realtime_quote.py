from sqlalchemy import Column, DateTime, Float, String

from .base import Base, BaseEntity


class FinanceRealtimeQuoteEntity(Base, BaseEntity):
    __tablename__ = "finance_realtime_quote"

    symbol = Column(String, primary_key=True)
    as_of = Column(DateTime(timezone=True), nullable=False)
    close = Column(Float, nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False)
