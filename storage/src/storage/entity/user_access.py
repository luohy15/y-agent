from sqlalchemy import CheckConstraint, Column, Integer, String, Text, UniqueConstraint

from .base import Base, BaseEntity


class UserAccessEntity(Base, BaseEntity):
    """One admission row per normalized verified email (todo 4396)."""

    __tablename__ = "user_access"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False)
    status = Column(String, nullable=False)
    source = Column(String, nullable=False)
    first_requested_at = Column(String, nullable=True)
    last_requested_at = Column(String, nullable=True)
    request_count = Column(Integer, nullable=False, default=0)
    decided_at = Column(String, nullable=True)
    decided_by = Column(String, nullable=True)
    notification_status = Column(String, nullable=False, default="pending")
    notification_attempts = Column(Integer, nullable=False, default=0)
    notified_at = Column(String, nullable=True)
    notification_claimed_at = Column(String, nullable=True)
    last_notification_attempt_at = Column(String, nullable=True)
    last_notification_error = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("email", name="uq_user_access_email"),
        CheckConstraint("status IN ('pending', 'approved')", name="ck_user_access_status"),
        CheckConstraint("source IN ('waitlist', 'rollout')", name="ck_user_access_source"),
        CheckConstraint(
            "notification_status IN ('pending', 'sending', 'sent', 'skipped', 'failed')",
            name="ck_user_access_notification_status",
        ),
        CheckConstraint("request_count >= 0", name="ck_user_access_request_count"),
        CheckConstraint("notification_attempts >= 0", name="ck_user_access_notification_attempts"),
    )
