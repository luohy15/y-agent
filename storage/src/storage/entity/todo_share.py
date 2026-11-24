from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint, CheckConstraint
from .base import Base, BaseEntity


class TodoShareEntity(Base, BaseEntity):
    __tablename__ = "todo_share"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    todo_id = Column(String, nullable=False)
    recipient_user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    share_id = Column(String, nullable=False, unique=True, index=True)
    revoked_at = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "todo_id", "recipient_user_id", name="uq_todo_share_owner_todo_recipient"),
    )


class TodoShareItemEntity(Base, BaseEntity):
    __tablename__ = "todo_share_item"

    id = Column(Integer, primary_key=True, autoincrement=True)
    share_id = Column(String, ForeignKey("todo_share.share_id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String, nullable=False)
    ref_id = Column(String, nullable=False)
    snapshot_key = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("share_id", "kind", "ref_id", name="uq_todo_share_item_ref"),
        CheckConstraint("kind IN ('note', 'chat', 'link')", name="ck_todo_share_item_kind"),
    )
