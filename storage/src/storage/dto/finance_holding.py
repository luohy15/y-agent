from dataclasses import dataclass
from typing import Optional


@dataclass
class FinanceHolding:
    id: Optional[int]
    user_id: int
    snapshot_at: str
    snapshot_date: str
    symbol: str
    quantity: float
    average_cost: Optional[float]
    price: Optional[float]
    book_value: Optional[float]
    market_value: Optional[float]
    unrealized_profit_pct: Optional[float]
    cost_currency: str
    is_cash: bool
    synced_at: str
    source: str

    def to_dict(self):
        return self.__dict__.copy()
