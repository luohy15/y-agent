from dataclasses import dataclass
from typing import Optional


@dataclass
class FinanceTransaction:
    id: Optional[int]
    user_id: int
    vm_name: str
    transaction_date: str
    entry_id: str
    posting_index: int
    account: str
    symbol: str
    side: str
    quantity: Optional[float]
    price: Optional[float]
    price_currency: str
    amount: Optional[float]
    amount_currency: str
    cost: Optional[float]
    cost_currency: str
    commission: Optional[float]
    commission_currency: str
    payee: str
    narration: str
    tags: list[str]
    links: list[str]
    synced_at: str
    source: str

    def to_dict(self):
        return self.__dict__.copy()
