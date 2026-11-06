from sqlalchemy import Column, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint
from storage.entity.base import Base, BaseEntity


class SkillBundleEntity(Base, BaseEntity):
    __tablename__ = 'skill_bundle'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    name = Column(String, nullable=False)
    bundle_sha = Column(String, nullable=False)
    manifest = Column(JSON, nullable=False)
    version = Column(String, nullable=True)
    __table_args__ = (UniqueConstraint('user_id', 'name', 'bundle_sha'),)


class SkillPinEntity(Base, BaseEntity):
    __tablename__ = 'skill_pin'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    name = Column(String, nullable=False)
    node = Column(String, nullable=False)
    bundle_sha = Column(String, nullable=False)
    __table_args__ = (
        UniqueConstraint('user_id', 'name', 'node'),
        ForeignKeyConstraint(['user_id', 'name', 'bundle_sha'],
                             ['skill_bundle.user_id', 'skill_bundle.name', 'skill_bundle.bundle_sha']),
    )
