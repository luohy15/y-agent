from sqlalchemy import CheckConstraint, Column, Integer, String, UniqueConstraint

from .base import Base, BaseEntity


class ModelContextWindowEntity(Base, BaseEntity):
    """Global badge denominator for one API model id.

    One row serves every bot. `init_db` creates the table and does not seed it;
    the only seed is the maintainer SQL for `gpt-6.1-sol`.
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
