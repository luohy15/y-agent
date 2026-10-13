from dataclasses import dataclass
from typing import Dict, Optional

# Chrome/WebKit cookie stores count microseconds since 1601-01-01; some
# browser_cookie3 versions pass that raw value through as `expires`.
_WEBKIT_EPOCH_OFFSET = 11644473600
_WEBKIT_THRESHOLD = 10 ** 14


def normalize_cookie_expiry(value: int) -> int:
    """Return a Netscape cookie expiry as Unix seconds (0 = session cookie)."""
    if value <= 0:
        return 0
    if value > _WEBKIT_THRESHOLD:
        return max(value // 1_000_000 - _WEBKIT_EPOCH_OFFSET, 0)
    return value


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
