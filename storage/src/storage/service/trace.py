from typing import Optional
from storage.dto.trace import Trace
from storage.repository import trace as trace_repo


def get_trace(user_id: int, trace_id: str) -> Optional[Trace]:
    return trace_repo.get_trace(user_id, trace_id)


def save_trace(user_id: int, trace: Trace) -> Trace:
    return trace_repo.save_trace(user_id, trace)
