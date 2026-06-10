from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class EmailAccount:
    address: str
    app_password: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self, include_password: bool = False) -> Dict:
        result = {
            "address": self.address,
        }
        if self.created_at is not None:
            result["created_at"] = self.created_at
        if self.updated_at is not None:
            result["updated_at"] = self.updated_at
        if include_password:
            result["app_password"] = self.app_password or ""
        return result
