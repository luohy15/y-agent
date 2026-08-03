from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class ModuleEntity(Base, BaseEntity):
    __tablename__ = "module"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    module_id = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    active_version_id = Column(String, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("user_id", "module_id"),
        UniqueConstraint("user_id", "slug"),
    )
