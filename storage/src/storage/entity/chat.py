from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, UniqueConstraint, CheckConstraint, Index, text
from .base import Base, BaseEntity


class ChatEntity(Base, BaseEntity):
    __tablename__ = "chat"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    chat_id = Column(String, nullable=False)
    title = Column(String, nullable=True)
    external_id = Column(String, nullable=True, index=True)
    backend = Column(String, nullable=True)
    bot_name = Column(String, nullable=True)
    tier = Column(String, nullable=True, index=True)
    origin_chat_id = Column(String, nullable=True, index=True)
    topic = Column(String, nullable=True, index=True)
    role = Column(String, nullable=True)
    skill = Column(String, nullable=True, index=True)
    trace_id = Column(String, nullable=True, index=True)
    routine_id = Column(String, nullable=True, index=True)
    # Sticky snapshot of the vm_config node name that runs this chat; NULL and
    # `default`/`ec2` all mean the orchestrator itself. See chat_target.
    execution_target = Column(String, nullable=True)
    json_content = Column(Text, nullable=False)
    search_text = Column(Text, nullable=True)  # extracted message text for fast search
    status = Column(String, nullable=False, server_default="idle")
    unread = Column(Boolean, nullable=False, server_default=text("false"))
    # Blocked-on-Roy signal, set explicitly by a running session (`y chat attention`)
    # rather than inferred. Display-only marker; does not influence list order
    # (todo 3141). See chat-core PRD.
    needs_attention = Column(Boolean, nullable=False, server_default=text("false"))
    share_password_hash = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "chat_id"),
        CheckConstraint("role IN ('manager', 'leader')", name="ck_chat_role"),
        # Portable subset of the migration's node-name format check
        # (`^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`); the regex CHECK is applied by
        # migration/4204_execution_node.sql so in-memory SQLite harnesses can
        # still create the table.
        CheckConstraint(
            "execution_target IS NULL OR (length(execution_target) BETWEEN 1 AND 64)",
            name="ck_chat_execution_target",
        ),
        Index("ix_chat_user_role_trace", "user_id", "role", "trace_id",
              postgresql_where=text("role IS NOT NULL")),
    )
