from typing import List, Optional, Tuple

from storage.dto.user_cookies import UserCookies
from storage.repository import user_cookies as user_cookies_repo


def normalize_domain(domain: str) -> str:
    value = (domain or "").strip().lower()
    value = value.removeprefix("http://").removeprefix("https://")
    value = value.split("/", 1)[0].split(":", 1)[0]
    return value.lstrip(".")


def _parse_cookie_stats(cookies_txt: str) -> Tuple[int, Optional[int]]:
    count = 0
    expiries: list[int] = []
    for raw_line in cookies_txt.splitlines():
        line = raw_line.strip()
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        count += 1
        try:
            expiry = int(parts[4])
        except ValueError:
            continue
        if expiry > 0:
            expiries.append(expiry)
    return count, min(expiries) if expiries else None


def upsert_cookies(user_id: int, domain: str, cookies_txt: str) -> UserCookies:
    normalized = normalize_domain(domain)
    count, expires_at_unix = _parse_cookie_stats(cookies_txt)
    return user_cookies_repo.upsert_for_user_domain(user_id, normalized, cookies_txt, expires_at_unix, count)


def get_cookies(user_id: int, domain: str) -> Optional[UserCookies]:
    row = user_cookies_repo.get_for_user_domain(user_id, normalize_domain(domain))
    if row is None:
        return None
    count, expires_at_unix = _parse_cookie_stats(row.cookies_txt or "")
    row.count = count
    row.expires_at = expires_at_unix
    return row


def list_cookies(user_id: int) -> List[UserCookies]:
    rows = user_cookies_repo.list_for_user(user_id)
    for row in rows:
        count, expires_at_unix = _parse_cookie_stats(row.cookies_txt or "")
        row.count = count
        row.expires_at = expires_at_unix
        row.cookies_txt = None
    return rows


def delete_cookies(user_id: int, domain: str) -> bool:
    return user_cookies_repo.delete_for_user_domain(user_id, normalize_domain(domain))
