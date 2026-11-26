from sqlalchemy import JSON, Column, Integer, String, ForeignKey, Index, UniqueConstraint, CheckConstraint, text
from .base import Base, BaseEntity


class TodoShareEntity(Base, BaseEntity):
    """One share row serves both audiences.

    ``recipient_user_id IS NULL`` is a public ``/t/:shareId`` link (optionally
    password-protected, with an optional ``selection`` JSON). ``IS NOT NULL`` is
    a private per-recipient grant backed by ``todo_share_item``.
    """

    __tablename__ = "todo_share"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    todo_id = Column(String, nullable=False)
    recipient_user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=True, index=True)
    share_id = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=True)
    revoked_at = Column(String, nullable=True)
    selection = Column(JSON(none_as_null=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "todo_id", "recipient_user_id", name="uq_todo_share_owner_todo_recipient"),
        Index(
            "uq_todo_share_public_owner_todo",
            "user_id",
            "todo_id",
            unique=True,
            postgresql_where=text("recipient_user_id IS NULL"),
        ),
        Index(
            "uq_todo_share_private_owner_todo_recipient",
            "user_id",
            "todo_id",
            "recipient_user_id",
            unique=True,
            postgresql_where=text("recipient_user_id IS NOT NULL"),
        ),
        CheckConstraint(
            "recipient_user_id IS NULL OR password_hash IS NULL",
            name="ck_todo_share_public_password",
        ),
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
