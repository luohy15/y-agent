from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from .base import Base, BaseEntity


class FinanceFundamentalsEntity(Base, BaseEntity):
    __tablename__ = "finance_fundamentals"

    symbol = Column(String, primary_key=True)
    overview = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    balance_sheet = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    income_statement = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    cash_flow = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    earnings = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    fetched_at = Column(DateTime(timezone=True), nullable=False)
