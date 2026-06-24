from dataclasses import dataclass
from typing import Optional


@dataclass
class ModelUsageDaily:
    id: Optional[int]
    user_id: int
    usage_date: str
    source: str
    provider: str
    model: str
    scope: str
    scope_id: str
    scope_name: str
    input_tokens: int
    output_tokens: int
    cache_create_tokens: int
    cache_read_tokens: int
    all_tokens: int
    requests: int
    cost: float
    cost_basis: str
    synced_at: str

    def to_dict(self):
        return self.__dict__.copy()
