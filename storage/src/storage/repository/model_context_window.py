"""Lookup for the global model context-window table."""

from typing import Optional

from storage.database.base import get_db
from storage.entity.model_context_window import ModelContextWindowEntity


def get_by_model(model: str) -> Optional[int]:
    """Return the window for an exact model id, or None when no row exists."""
    with get_db() as session:
        return (
            session.query(ModelContextWindowEntity.context_window)
            .filter(ModelContextWindowEntity.model == model)
            .scalar()
        )
