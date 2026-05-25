from sqlalchemy import JSON, Column, Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from .base import Base, BaseEntity


class FinanceTransactionEntity(Base, BaseEntity):
    __tablename__ = "finance_transaction"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    transaction_date = Column(Date, nullable=False)
    entry_id = Column(String, nullable=False)
    posting_index = Column(Integer, nullable=False, default=0)
    account = Column(String, nullable=False, default="")
    symbol = Column(String, nullable=False, default="")
    side = Column(String, nullable=False, default="Unknown")
    quantity = Column(Float, nullable=True)
    price = Column(Float, nullable=True)
    price_currency = Column(String, nullable=False, default="")
    amount = Column(Float, nullable=True)
    amount_currency = Column(String, nullable=False, default="")
    cost = Column(Float, nullable=True)
    cost_currency = Column(String, nullable=False, default="")
    commission = Column(Float, nullable=True)
    commission_currency = Column(String, nullable=False, default="")
    payee = Column(Text, nullable=False, default="")
    narration = Column(Text, nullable=False, default="")
    tags = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    links = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    synced_at = Column(String, nullable=False)
    source = Column(String, nullable=False, default="sync")

    __table_args__ = (
        UniqueConstraint("user_id", "entry_id", "posting_index", name="uq_finance_transaction_posting"),
        Index("ix_finance_transaction_user_date", "user_id", "transaction_date"),
        Index("ix_finance_transaction_user_symbol", "user_id", "symbol"),
    )
