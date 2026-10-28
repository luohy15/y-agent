from sqlalchemy import BigInteger, Boolean, Column, ForeignKey, Integer, JSON

from .base import Base, BaseEntity


class TraceRuntimeSnapshotEntity(Base, BaseEntity):
    """Last runtime probe per owner (todo 4070).

    Worker-written evidence only: `ok=False` means the probe was unknown, not
    that nothing runs. The list read and the watchdog decision both derive from
    this row, and no API/CLI/module path may write it.
    """

    __tablename__ = "trace_runtime_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, unique=True)
    observed_at_unix = Column(BigInteger, nullable=False)
    ok = Column(Boolean, nullable=False)
    jobs = Column(JSON, nullable=False)
