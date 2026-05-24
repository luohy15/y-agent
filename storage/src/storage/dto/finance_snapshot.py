from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class FinanceSnapshot:
    user_id: int
    vm_name: str
    view: str
    time_filter: str
    history: bool
    granularity: str
    convert: str
    payload: Any
    synced_at: str
    source: str = "sync"
    last_error: Optional[str] = None
    id: Optional[int] = None

    def to_dict(self) -> Dict:
        return {
            "data": self.payload,
            "synced_at": self.synced_at,
            "source": self.source,
        }
