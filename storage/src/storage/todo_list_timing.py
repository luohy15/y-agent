"""Opt-in stage timing for GET /api/todo/list (todo 3788 R1).

Off unless `Y_AGENT_TODO_LIST_TIMING=1`. When on, each request to the route
logs one `todo_list_timing` line with stage durations and bounded shape
buckets only: status allowlist, limit bucket, history flag, returned-count
bucket, first route use in this process, and outcome. It never logs query
values, ids, SQL, URLs, tokens or payloads.

`handler_ms` is measured on its own from handler entry to the built response.
It is not the sum of the stages, and it is not the monitor duration (which
also covers middleware, auth and response send).

State lives in a ContextVar, so concurrent requests never share timings.
"""

import json
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Dict, Optional

from loguru import logger

ENV_FLAG = "Y_AGENT_TODO_LIST_TIMING"
EVENT = "todo_list_timing"
STATUSES = frozenset({"pending", "active", "awaiting", "completed", "deleted"})

_clock = time.perf_counter


class _Timing:
    __slots__ = ("started", "first_use", "stages")

    def __init__(self, started: float, first_use: bool):
        self.started = started
        self.first_use = first_use
        self.stages: Dict[str, float] = {}


_current: ContextVar[Optional[_Timing]] = ContextVar("todo_list_timing", default=None)
_route_used = False


def begin() -> Optional[Token]:
    """Start timing this request. Returns None (and records nothing) when off."""
    global _route_used
    first_use = not _route_used
    _route_used = True
    if os.getenv(ENV_FLAG) != "1":
        return None
    return _current.set(_Timing(_clock(), first_use))


def active() -> bool:
    return _current.get() is not None


@contextmanager
def stage(name: str):
    timing = _current.get()
    if timing is None:
        yield
        return
    started = _clock()
    try:
        yield
    finally:
        timing.stages[name] = timing.stages.get(name, 0.0) + (_clock() - started)


def mark() -> Optional[float]:
    """Clock reading for a stage that spans a `with` boundary, None when off."""
    return _clock() if _current.get() is not None else None


def add_since(name: str, started: Optional[float]) -> None:
    timing = _current.get()
    if timing is None or started is None:
        return
    timing.stages[name] = timing.stages.get(name, 0.0) + (_clock() - started)


def _status_bucket(status: Optional[str]) -> str:
    if not status:
        return "none"
    return status if status in STATUSES else "other"


def _limit_bucket(limit: int) -> str:
    if limit <= 20:
        return "le20"
    if limit <= 50:
        return "le50"
    if limit <= 100:
        return "le100"
    return "gt100"


def _count_bucket(count: Optional[int]) -> Optional[str]:
    if count is None:
        return None
    if count == 0:
        return "0"
    if count <= 5:
        return "1-5"
    if count <= 20:
        return "6-20"
    if count <= 50:
        return "21-50"
    return "gt50"


def _ms(seconds: float) -> float:
    return round(seconds * 1000, 3)


def finish(
    token: Optional[Token],
    *,
    status: Optional[str],
    limit: int,
    include_history: bool,
    count: Optional[int],
    ok: bool,
) -> None:
    if token is None:
        return
    timing = _current.get()
    _current.reset(token)
    if timing is None:
        return
    payload = {
        "event": EVENT,
        "v": 1,
        "outcome": "ok" if ok else "error",
        "status": _status_bucket(status),
        "limit": _limit_bucket(limit),
        "history": bool(include_history),
        "count": _count_bucket(count),
        "first_use": timing.first_use,
        "stages_ms": {name: _ms(value) for name, value in timing.stages.items()},
        "handler_ms": _ms(_clock() - timing.started),
    }
    logger.info("{} {}", EVENT, json.dumps(payload, sort_keys=True))
