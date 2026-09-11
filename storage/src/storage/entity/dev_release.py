from sqlalchemy import (
    Boolean, CheckConstraint, Column, ForeignKey, Integer, JSON, String, UniqueConstraint
)
from .base import Base, BaseEntity


class DevReleaseEntity(Base, BaseEntity):
    """One persistent publication slot per canonical project (todo 3493).

    The row is never deleted: releasing a claim clears the owner columns but
    keeps the monotonically increasing ``generation`` and the transition
    history, so a delayed request carrying an old generation or claim can never
    resurrect ownership. ``project_key`` alone is unique -- the slot is global
    per repository, so two accounts cannot hold independent slots for it, while
    ``user_id`` records which account may mutate the current claim.

    The FK deliberately restricts user deletion instead of cascading: dropping
    a user must not silently release an active claim.
    """

    __tablename__ = "dev_release"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_key = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='RESTRICT'), nullable=True, index=True)
    claim_id = Column(String, nullable=True)
    generation = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=False)
    owner_trace_id = Column(String, nullable=True)
    owner_chat_id = Column(String, nullable=True)
    publisher_chat_id = Column(String, nullable=True)
    target = Column(String, nullable=True)
    history = Column(JSON, nullable=False, default=list)
    # Ordered FIFO of pending waiter ids (todo 3493 revision). Only the order
    # lives here; every waiter's durable state and registration parameters are
    # rows in `dev_release_waiter`, so a receipt survives leaving the queue.
    waiters = Column(JSON, nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint("project_key", name="uq_dev_release_project_key"),
        CheckConstraint("generation >= 0", name="ck_dev_release_generation_nonnegative"),
        CheckConstraint(
            "(active AND user_id IS NOT NULL AND claim_id IS NOT NULL"
            " AND owner_trace_id IS NOT NULL AND owner_chat_id IS NOT NULL)"
            " OR (NOT active AND user_id IS NULL AND claim_id IS NULL"
            " AND owner_trace_id IS NULL AND owner_chat_id IS NULL"
            " AND publisher_chat_id IS NULL)",
            name="ck_dev_release_active_owner_consistency",
        ),
    )
