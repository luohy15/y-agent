from sqlalchemy import Column, ForeignKey, Integer, JSON, String, UniqueConstraint

from .base import Base, BaseEntity


class BotRouteStateEntity(Base, BaseEntity):
    """Persisted smooth weighted round-robin state for a user's tier."""

    __tablename__ = "bot_route_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    tier = Column(String, nullable=False)
    pool_key = Column(String, nullable=False)
    candidate_weights = Column(JSON, nullable=False)
    current_weights = Column(JSON, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "tier", "pool_key", name="uq_bot_route_state_user_tier_pool"),
    )
