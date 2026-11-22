from sqlalchemy import CheckConstraint, Column, Integer, String, UniqueConstraint

from .base import Base, BaseEntity


class ModelContextWindowEntity(Base, BaseEntity):
    """Global badge denominator for one API model id.

    One row serves every bot. `init_db` creates the table and does not seed it.
    Rows come from maintainer SQL or the add-only catalog sync. Codex closeout
    uses a row only when the rollout did not report its own window.
    """

    __tablename__ = "model_context_window"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model = Column(String, nullable=False)
    context_window = Column(Integer, nullable=False)
    note = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("model", name="uq_model_context_window_model"),
        CheckConstraint("context_window > 0", name="ck_model_context_window_positive"),
    )
