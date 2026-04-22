"""Helpers for optional share-link passwords.

Hashing reuses bcrypt (already a dep via UserEntity). Verification is rate-limited
per share_id using an in-process sliding window — on Lambda this resets on cold
starts, but bcrypt's work factor alone makes brute force costly enough for a
personal-scope project.
"""

import secrets
import time
from collections import deque
from typing import Deque, Dict, Tuple

_RATE_LIMIT_WINDOW_SEC = 60.0
_RATE_LIMIT_MAX_FAILURES = 10
_failures: Dict[str, Deque[float]] = {}


def generate_password() -> str:
    return secrets.token_urlsafe(12)


def hash_password(plaintext: str) -> str:
    import bcrypt
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plaintext: str, hashed: str) -> bool:
    if not hashed:
        return False
    import bcrypt
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _prune(share_id: str, now: float) -> Deque[float]:
    dq = _failures.setdefault(share_id, deque())
    cutoff = now - _RATE_LIMIT_WINDOW_SEC
    while dq and dq[0] < cutoff:
        dq.popleft()
    return dq


def check_rate_limit(share_id: str) -> Tuple[bool, int]:
    """Return (allowed, retry_after_sec). retry_after only meaningful if blocked."""
    now = time.time()
    dq = _prune(share_id, now)
    if len(dq) >= _RATE_LIMIT_MAX_FAILURES:
        retry = max(1, int(_RATE_LIMIT_WINDOW_SEC - (now - dq[0])))
        return False, retry
    return True, 0


def record_failure(share_id: str) -> None:
    now = time.time()
    dq = _prune(share_id, now)
    dq.append(now)
