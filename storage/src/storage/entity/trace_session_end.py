from sqlalchemy import (BigInteger, CheckConstraint, Column, ForeignKey, Index,
                        Integer, String, UniqueConstraint)

from .base import Base, BaseEntity


class TraceSessionEndEntity(Base, BaseEntity):
    """One normal-session-end reconcile outcome (todo 4077).

    Worker-written only. `run_key` is the closeout identity
    (`str(proc["started_at"])`); the unique key makes duplicate closeouts
    idempotent. `disposition` records what the reconcile did: `awaiting` means
    this call claimed the todo, `active` kept it active with `evidence` naming
    the suppressor, `not_active` found it outside `active`, `unknown` could not
    prove anything, and `failed` hit an error.
    """

    __tablename__ = "trace_session_end"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    chat_id = Column(String, nullable=False)
    trace_id = Column(String, nullable=False)
    run_key = Column(String, nullable=False)
    ended_at_unix = Column(BigInteger, nullable=False)
    disposition = Column(String, nullable=False)
    evidence = Column(String, nullable=True)
    runtime_observed_at_unix = Column(BigInteger, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "chat_id", "run_key", name="uq_trace_session_end_run"),
        CheckConstraint(
            "disposition IN ('awaiting', 'active', 'not_active', 'unknown', 'failed')",
            name="ck_trace_session_end_disposition",
        ),
        CheckConstraint(
            "evidence IS NULL OR evidence IN ('session', 'child', 'tmux', 'process', 'waiter', 'wakeup', 'stale_row')",
            name="ck_trace_session_end_evidence",
        ),
        Index("ix_trace_session_end_user_trace_ended", "user_id", "trace_id", "ended_at_unix"),
    )
