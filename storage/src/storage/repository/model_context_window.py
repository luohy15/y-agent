"""Lookup for the global model context-window table."""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from storage.database.base import get_db
from storage.entity.model_context_window import ModelContextWindowEntity


def list_models() -> set[str]:
    with get_db() as session:
        return set(session.scalars(select(ModelContextWindowEntity.model)))


def insert_missing(rows: list[dict]) -> list[str]:
    if not rows:
        return []
    table = ModelContextWindowEntity.__table__
    statement = insert(table).values(rows).on_conflict_do_nothing(index_elements=[table.c.model])
    with get_db() as session:
        return sorted(session.scalars(statement.returning(table.c.model)))


def get_by_model(model: str) -> Optional[int]:
    """Return the window for an exact model id, or None when no row exists."""
    with get_db() as session:
        return (
            session.query(ModelContextWindowEntity.context_window)
            .filter(ModelContextWindowEntity.model == model)
            .scalar()
        )
