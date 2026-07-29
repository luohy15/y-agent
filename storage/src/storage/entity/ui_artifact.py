from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class UiArtifactEntity(Base, BaseEntity):
    __tablename__ = "ui_artifact"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    artifact_id = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    kind = Column(String, nullable=False, default="panel")
    active_version_id = Column(String, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("user_id", "artifact_id"),
        UniqueConstraint("user_id", "slug"),
    )
