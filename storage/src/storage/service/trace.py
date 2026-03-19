from typing import List, Optional
from storage.dto.trace import Trace
from storage.repository import trace as trace_repo
from storage.repository.trace import TraceSummary


async def list_traces(user_id: int, limit: int = 50, offset: int = 0) -> List[TraceSummary]:
    return await trace_repo.list_traces(user_id, limit=limit, offset=offset)


def get_trace(user_id: int, trace_id: str) -> Optional[Trace]:
    return trace_repo.get_trace(user_id, trace_id)


def find_trace_by_chat_id(user_id: int, chat_id: str) -> Optional[Trace]:
    return trace_repo.find_trace_by_chat_id(user_id, chat_id)


def save_trace(user_id: int, trace: Trace) -> Trace:
    return trace_repo.save_trace(user_id, trace)
