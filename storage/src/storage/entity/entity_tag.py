from sqlalchemy import Column, Index, Integer, String, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class EntityTagEntity(Base, BaseEntity):
    __tablename__ = "entity_tag"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    tag = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "entity_type", "entity_id", "tag"),
        # Cross-entity find-by-tag + range roll-up (mirrors migration/2838_entity_tag.sql).
        Index("ix_entity_tag_user_tag", "user_id", "tag"),
        # Prefix roll-up (e.g. LIKE 'work/%'); postgresql_ops is a no-op on non-Postgres
        # dialects, so this stays safe for Base.metadata.create_all() on SQLite in tests.
        Index(
            "ix_entity_tag_user_tag_pat", "user_id", "tag",
            postgresql_ops={"tag": "varchar_pattern_ops"},
        ),
        # Per-entity read (list_tags / delete_for_entity).
        Index("ix_entity_tag_user_type_entity", "user_id", "entity_type", "entity_id"),
    )
