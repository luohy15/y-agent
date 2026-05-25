from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String

from .base import Base, BaseEntity


class FinanceHoldingEntity(Base, BaseEntity):
    __tablename__ = "finance_holding"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    snapshot_at = Column(DateTime(timezone=True), nullable=False)
    symbol = Column(String, nullable=False)
    quantity = Column(Float, nullable=False, default=0)
    average_cost = Column(Float, nullable=True)
    price = Column(Float, nullable=True)
    book_value = Column(Float, nullable=True)
    market_value = Column(Float, nullable=True)
    unrealized_profit_pct = Column(Float, nullable=True)
    cost_currency = Column(String, nullable=False, default="")
    is_cash = Column(Boolean, nullable=False, default=False)
    synced_at = Column(String, nullable=False)
    source = Column(String, nullable=False, default="sync")

    __table_args__ = (
        Index("ix_finance_holding_user_snapshot", "user_id", "snapshot_at"),
        Index("ix_finance_holding_user_symbol", "user_id", "symbol"),
    )
