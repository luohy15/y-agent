from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class UserCookies:
    domain: str
    cookies_txt: Optional[str] = None
    count: int = 0
    expires_at: Optional[int] = None
    updated_at: Optional[str] = None
    updated_at_unix: Optional[int] = None

    def to_dict(self, include_blob: bool = True) -> Dict:
        result = {
            "domain": self.domain,
            "count": self.count,
            "expires_at": self.expires_at,
            "updated_at": self.updated_at,
        }
        if self.updated_at_unix is not None:
            result["updated_at_unix"] = self.updated_at_unix
        if include_blob:
            result["cookies_txt"] = self.cookies_txt or ""
        return result
