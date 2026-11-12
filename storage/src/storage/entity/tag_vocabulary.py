from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from .base import Base, BaseEntity


class TagVocabularyEntity(Base, BaseEntity):
    """Durable, owner-scoped canonical tag registry (todo 3290).

    Unlike entity_tag (a usage projection over carriers), a row here can exist
    with zero entity_tag uses: creating a tag is a first-class action, not
    something inferred only from tagging a carrier. Membership writes require
    existing vocabulary under the owner lock (see storage.repository.entity_tag).
    Only explicit creation and coordinated rename register new spellings, so
    membership writes cannot introduce unknown tags.
    """

    __tablename__ = "tag_vocabulary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    tag = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "tag"),
    )
