from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class UserPreference:
    key: str
    value: Optional[Any] = None
    updated_at: Optional[str] = None
    updated_at_unix: Optional[int] = None

    def to_dict(self) -> Dict:
        result: Dict[str, Any] = {
            "key": self.key,
            "value": self.value,
        }
        if self.updated_at is not None:
            result["updated_at"] = self.updated_at
        if self.updated_at_unix is not None:
            result["updated_at_unix"] = self.updated_at_unix
        return result
