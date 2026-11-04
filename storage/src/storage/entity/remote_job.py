from sqlalchemy import BigInteger, Boolean, Column, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from .base import Base, BaseEntity


class ExecutionTargetEntity(Base, BaseEntity):
    __tablename__ = 'execution_target'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    target_id = Column(String, nullable=False)
    transport_kind = Column(String, nullable=False)
    transport_ref = Column(String, nullable=False)
    platform = Column(String, nullable=False)
    executors = Column(JSONB, nullable=False)
    operations = Column(JSONB, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    __table_args__ = (UniqueConstraint('user_id', 'target_id', name='uq_execution_target_owner'),)


class RemoteJobEntity(Base, BaseEntity):
    __tablename__ = 'remote_job'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    job_id = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    executor = Column(String, nullable=False, default='codex')
    operation = Column(String, nullable=False)
    payload = Column(JSONB, nullable=False)
    target_snapshot = Column(JSONB, nullable=False)
    timeout_seconds = Column(Integer, nullable=False, default=180)
    state = Column(String, nullable=False, default='queued')
    attempt = Column(Integer, nullable=False, default=0)
    claim_token = Column(String)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    started_at = Column(String)
    heartbeat_at_unix = Column(BigInteger)
    finished_at = Column(String)
    exit_code = Column(Integer)
    error_code = Column(String)
    error = Column(Text)
    stdout = Column(Text)
    stderr = Column(Text)
    result = Column(JSONB)
    artifacts = Column(JSONB)
    todo_id = Column(String)
    trace_id = Column(String)
    callback_chat_id = Column(String)
    __table_args__ = (
        UniqueConstraint('user_id', 'job_id', name='uq_remote_job_owner'),
        Index('ix_remote_job_owner_created', 'user_id', 'created_at_unix'),
        Index('ix_remote_job_state', 'state'),
    )
