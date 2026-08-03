from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class ModuleVersionEntity(Base, BaseEntity):
    """Immutable once inserted: only module.active_version_id / enabled ever change after a publish."""

    __tablename__ = "module_version"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    version_id = Column(String, nullable=False)
    module_id = Column(String, nullable=False, index=True)

    version_no = Column(Integer, nullable=False)
    ui_sha256 = Column(String, nullable=True)
    ui_storage_key = Column(String, nullable=True)
    api_sha256 = Column(String, nullable=True)
    api_storage_key = Column(String, nullable=True)
    label = Column(String, nullable=True)
    icon = Column(String, nullable=True)
    min_host_version = Column(Integer, nullable=False, default=1)
    min_backend_version = Column(Integer, nullable=True)
    source_digest = Column(String, nullable=True)
    built_at = Column(String, nullable=True)
    description = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "version_id"),
        UniqueConstraint("user_id", "module_id", "version_no"),
    )
