from typing import List, Optional

from storage.database.base import get_db
from storage.entity.trace_share import TraceShareEntity


def get_by_share_id(share_id: str) -> Optional[TraceShareEntity]:
    with get_db() as session:
        return session.query(TraceShareEntity).filter_by(share_id=share_id).first()


def get_by_trace_id(user_id: int, trace_id: str) -> Optional[TraceShareEntity]:
    with get_db() as session:
        return session.query(TraceShareEntity).filter_by(user_id=user_id, trace_id=trace_id).first()


def create(user_id: int, share_id: str, trace_id: str, password_hash: Optional[str] = None) -> TraceShareEntity:
    with get_db() as session:
        entity = TraceShareEntity(
            user_id=user_id,
            share_id=share_id,
            trace_id=trace_id,
            password_hash=password_hash,
        )
        session.add(entity)
        session.flush()
        session.expunge(entity)
        return entity


def set_password_hash(share_id: str, password_hash: Optional[str]) -> None:
    with get_db() as session:
        session.query(TraceShareEntity).filter_by(share_id=share_id).update(
            {"password_hash": password_hash}
        )


def delete_by_share_id(share_id: str) -> int:
    with get_db() as session:
        return session.query(TraceShareEntity).filter_by(share_id=share_id).delete()


def list_by_user(user_id: int) -> List[TraceShareEntity]:
    with get_db() as session:
        entities = session.query(TraceShareEntity).filter_by(user_id=user_id).order_by(TraceShareEntity.id.desc()).all()
        for e in entities:
            session.expunge(e)
        return entities
