from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class UiArtifactVersionEntity(Base, BaseEntity):
    """Immutable once inserted: only ui_artifact.active_version_id / enabled ever change after a publish."""

    __tablename__ = "ui_artifact_version"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    version_id = Column(String, nullable=False)
    artifact_id = Column(String, nullable=False, index=True)

    version_no = Column(Integer, nullable=False)
    sha256 = Column(String, nullable=False)
    storage_key = Column(String, nullable=False)
    label = Column(String, nullable=True)
    icon = Column(String, nullable=True)
    min_host_version = Column(Integer, nullable=False, default=1)
    source_digest = Column(String, nullable=True)
    built_at = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "version_id"),
        UniqueConstraint("user_id", "artifact_id", "version_no"),
    )
