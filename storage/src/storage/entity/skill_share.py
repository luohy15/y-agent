from sqlalchemy import Column, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint
from storage.entity.base import Base, BaseEntity


class SkillEntity(Base, BaseEntity):
    __tablename__ = 'skill'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    name = Column(String, nullable=False)
    latest_version = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint('user_id', 'name'),)


class SkillVersionEntity(Base, BaseEntity):
    __tablename__ = 'skill_version'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    bundle_sha = Column(String, nullable=False)
    manifest = Column(JSON, nullable=False)
    source_commit = Column(String, nullable=False)
    source_repo = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint('user_id', 'name', 'version'),)


class SkillInstallEntity(Base, BaseEntity):
    __tablename__ = 'skill_install'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    name = Column(String, nullable=False)
    node = Column(String, nullable=False)
    version = Column(String, nullable=False)
    previous_version = Column(String, nullable=True)
    __table_args__ = (
        UniqueConstraint('user_id', 'name', 'node'),
        ForeignKeyConstraint(['user_id', 'name', 'version'],
                             ['skill_version.user_id', 'skill_version.name', 'skill_version.version']),
        ForeignKeyConstraint(['user_id', 'name', 'previous_version'],
                             ['skill_version.user_id', 'skill_version.name', 'skill_version.version']),
    )
