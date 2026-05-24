from sqlalchemy import Column, Date, Float, ForeignKey, Index, Integer, String, UniqueConstraint

from .base import Base, BaseEntity


class FinancePriceEntity(Base, BaseEntity):
    __tablename__ = "finance_price"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    vm_name = Column(String, nullable=False, default="")
    symbol = Column(String, nullable=False)
    price_date = Column(Date, nullable=False)
    price = Column(Float, nullable=False)
    currency = Column(String, nullable=False, default="")
    synced_at = Column(String, nullable=False)
    source = Column(String, nullable=False, default="sync")

    __table_args__ = (
        UniqueConstraint("user_id", "vm_name", "symbol", "price_date", "currency", name="uq_finance_price_daily"),
        Index("ix_finance_price_user_vm_symbol_date", "user_id", "vm_name", "symbol", "price_date"),
    )
