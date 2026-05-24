from sqlalchemy import JSON, Column, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from .base import Base, BaseEntity


class FinanceSnapshotEntity(Base, BaseEntity):
    __tablename__ = "finance_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    vm_name = Column(String, nullable=False, default="")
    view = Column(String, nullable=False)
    time_filter = Column(String, nullable=False, default="")
    history = Column(String, nullable=False, default="false")
    granularity = Column(String, nullable=False, default="")
    convert = Column(String, nullable=False, default="")
    payload = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    synced_at = Column(String, nullable=False)
    source = Column(String, nullable=False, default="sync")
    last_error = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "vm_name",
            "view",
            "time_filter",
            "history",
            "granularity",
            "convert",
            name="uq_finance_snapshot_key",
        ),
    )
