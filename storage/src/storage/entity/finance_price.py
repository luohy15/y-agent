from sqlalchemy import Column, Date, Float, Index, Integer, String, UniqueConstraint

from .base import Base, BaseEntity


class FinancePriceEntity(Base, BaseEntity):
    __tablename__ = "finance_price"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    price_date = Column(Date, nullable=False)
    price = Column(Float, nullable=False)
    currency = Column(String, nullable=False, default="")
    synced_at = Column(String, nullable=False)
    source = Column(String, nullable=False, default="sync")

    __table_args__ = (
        UniqueConstraint("symbol", "price_date", "currency", name="uq_finance_price_daily"),
        Index("ix_finance_price_symbol_date", "symbol", "price_date"),
    )
