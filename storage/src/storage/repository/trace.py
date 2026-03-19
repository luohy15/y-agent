"""Function-based trace repository using SQLAlchemy sessions."""

from dataclasses import dataclass
from typing import List, Optional
from storage.entity.trace import TraceEntity
from storage.dto.trace import Trace, TraceParticipant
from storage.database.base import get_db


@dataclass
class TraceSummary:
    trace_id: str
    participants: list
    created_at: str
    updated_at: str


def _entity_to_dto(entity: TraceEntity) -> Trace:
    participants = entity.participants or []
    return Trace(
        trace_id=entity.trace_id,
        participants=[TraceParticipant.from_dict(p) for p in participants],
        created_at=entity.created_at if entity.created_at else None,
        updated_at=entity.updated_at if entity.updated_at else None,
    )


async def list_traces(user_id: int, limit: int = 50, offset: int = 0) -> List[TraceSummary]:
    with get_db() as session:
        rows = (session.query(TraceEntity)
                .filter_by(user_id=user_id)
                .order_by(TraceEntity.updated_at.desc())
                .offset(offset)
                .limit(limit)
                .all())
        return [
            TraceSummary(
                trace_id=row.trace_id,
                participants=row.participants or [],
                created_at=row.created_at or "",
                updated_at=row.updated_at or "",
            )
            for row in rows
        ]


def get_trace(user_id: int, trace_id: str) -> Optional[Trace]:
    with get_db() as session:
        row = session.query(TraceEntity).filter_by(user_id=user_id, trace_id=trace_id).first()
        if row:
            return _entity_to_dto(row)
        return None


def save_trace(user_id: int, trace: Trace) -> Trace:
    with get_db() as session:
        entity = session.query(TraceEntity).filter_by(user_id=user_id, trace_id=trace.trace_id).first()
        fields = dict(
            participants=[p.to_dict() for p in trace.participants],
        )
        if entity:
            for k, v in fields.items():
                setattr(entity, k, v)
        else:
            entity = TraceEntity(user_id=user_id, trace_id=trace.trace_id, **fields)
            session.add(entity)
        session.flush()
        return _entity_to_dto(entity)
