from dataclasses import dataclass
from typing import Optional


@dataclass
class FinancePrice:
    id: Optional[int]
    user_id: int
    vm_name: str
    symbol: str
    price_date: str
    price: float
    currency: str
    synced_at: str
    source: str

    def to_dict(self):
        return self.__dict__.copy()
