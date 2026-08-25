from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class TagVocabularyEntity(Base, BaseEntity):
    """Durable, owner-scoped canonical tag registry (todo 3290).

    Unlike entity_tag (a usage projection over carriers), a row here can exist
    with zero entity_tag uses: creating a tag is a first-class action, not
    something inferred only from tagging a carrier. Every normalized
    entity_tag write also registers its tag here in the same transaction (see
    storage.repository.entity_tag), so distinct entity_tag.tag values for a
    user are always a subset of that user's tag_vocabulary.tag values.
    """

    __tablename__ = "tag_vocabulary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    tag = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "tag"),
    )
