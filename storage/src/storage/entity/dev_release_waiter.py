from sqlalchemy import (
    Boolean, CheckConstraint, Column, ForeignKey, Index, Integer, JSON, String,
    UniqueConstraint, text
)
from .base import Base, BaseEntity


class DevReleaseWaiterEntity(Base, BaseEntity):
    """Durable receipt for one authorized waiter on a project slot (todo 3493).

    The slot's `waiters` JSON holds only pending ids in FIFO order; this table
    holds the state a late retry must still find after the id has left that
    queue. That is what makes a delayed registration or cancellation retry
    safe: a cancelled or already-served waiter is a permanent tombstone here,
    while the slot's bounded transition history may already have trimmed the
    event.

    It also carries the frozen candidate attestation (authorization reference,
    target, baseline/candidate SHA, included todos) and the durable grant
    wakeup event, so ownership and "this chat must be woken" commit together.
    """

    __tablename__ = "dev_release_waiter"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_key = Column(String, nullable=False, index=True)
    waiter_id = Column(String, nullable=False)
    request_id = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='RESTRICT'), nullable=False, index=True)
    trace_id = Column(String, nullable=False)
    chat_id = Column(String, nullable=False)

    # Frozen candidate identity. An attestation recorded on the caller's word,
    # never server verification that Roy authorized this delta.
    target = Column(String, nullable=True)
    authorization_reference = Column(String, nullable=False)
    baseline_sha = Column(String, nullable=False)
    candidate_sha = Column(String, nullable=False)
    todo_ids = Column(JSON, nullable=False, default=list)

    status = Column(String, nullable=False, default="pending")
    rejected_reason = Column(String, nullable=True)
    cancel_request_id = Column(String, nullable=True)

    granted_claim_id = Column(String, nullable=True)
    granted_generation = Column(Integer, nullable=True)

    # Grant wakeup event, written in the same transaction as ownership.
    event_id = Column(String, nullable=True)
    delivery_state = Column(String, nullable=True)
    enqueue_needed = Column(Boolean, nullable=True)
    delivery_attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("project_key", "waiter_id", name="uq_dev_release_waiter_id"),
        UniqueConstraint("project_key", "request_id", name="uq_dev_release_waiter_request"),
        CheckConstraint(
            "status IN ('pending', 'granted', 'cancelled', 'rejected')",
            name="ck_dev_release_waiter_status",
        ),
        CheckConstraint(
            "delivery_state IS NULL OR delivery_state IN "
            "('pending', 'accepted', 'sent', 'superseded', 'failed')",
            name="ck_dev_release_waiter_delivery_state",
        ),
        CheckConstraint("delivery_attempts >= 0", name="ck_dev_release_waiter_attempts"),
        # The outbox recovery pass scans exactly this predicate; declared here
        # so a database built from init_tables has the same shape as the SQL.
        Index("ix_dev_release_waiter_delivery", "delivery_state",
              postgresql_where=text("event_id IS NOT NULL")),
    )
