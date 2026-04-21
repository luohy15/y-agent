from sqlalchemy import Column, String
from .base import Base


class PipelineLockEntity(Base):
    __tablename__ = "pipeline_lock"

    action = Column(String, primary_key=True)
    locked_at = Column(String, nullable=False)
