from typing import Optional

from storage.database.base import get_db
from storage.entity.trace_share import TraceShareEntity


def get_by_share_id(share_id: str) -> Optional[TraceShareEntity]:
    with get_db() as session:
        return session.query(TraceShareEntity).filter_by(share_id=share_id).first()


def get_by_trace_id(user_id: int, trace_id: str) -> Optional[TraceShareEntity]:
    with get_db() as session:
        return session.query(TraceShareEntity).filter_by(user_id=user_id, trace_id=trace_id).first()


def create(user_id: int, share_id: str, trace_id: str) -> TraceShareEntity:
    with get_db() as session:
        entity = TraceShareEntity(user_id=user_id, share_id=share_id, trace_id=trace_id)
        session.add(entity)
        session.flush()
        # Detach from session before returning
        session.expunge(entity)
        return entity
