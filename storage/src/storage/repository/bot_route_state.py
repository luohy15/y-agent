"""Persisted smooth weighted round-robin bot routing state."""

import hashlib
import json
from typing import List, Optional, Tuple

from storage.database.base import get_db
from storage.entity.bot_route_state import BotRouteStateEntity
from storage.entity.user import UserEntity


def _next_selection(candidates: List[Tuple[str, float]], current_weights: dict) -> Tuple[str, dict]:
    """Return the next smooth weighted round-robin candidate and state."""
    total_weight = sum(weight for _, weight in candidates)
    next_weights = {
        name: float(current_weights.get(name, 0)) + weight
        for name, weight in candidates
    }
    selected_name = max(candidates, key=lambda item: (next_weights[item[0]], item[0]))[0]
    next_weights[selected_name] -= total_weight
    return selected_name, next_weights


def _pool_key(candidates: List[Tuple[str, float]]) -> str:
    """Return a stable key for an effective candidate pool and its weights."""
    payload = json.dumps(candidates, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def select_weighted_round_robin(user_id: int, tier: str, candidates: List[Tuple[str, float]]) -> Optional[str]:
    """Select and persist the next smooth weighted round-robin candidate.

    The row lock makes concurrent dispatches for the same user and tier share
    one sequence per effective candidate pool. Candidate weights are sorted by
    name so configuration query order does not affect the schedule. Filtered
    pools receive their own state and cannot reset a full-tier sequence.
    """
    eligible = sorted((name, float(weight)) for name, weight in candidates if weight > 0)
    if not eligible:
        return None

    candidate_weights = {name: weight for name, weight in eligible}
    pool_key = _pool_key(eligible)

    with get_db() as session:
        session.query(UserEntity).filter_by(id=user_id).with_for_update().first()
        state = (
            session.query(BotRouteStateEntity)
            .filter_by(user_id=user_id, tier=tier, pool_key=pool_key)
            .with_for_update()
            .first()
        )
        if state is None:
            state = BotRouteStateEntity(
                user_id=user_id,
                tier=tier,
                pool_key=pool_key,
                candidate_weights=candidate_weights,
                current_weights={},
            )
            session.add(state)

        selected_name, state.current_weights = _next_selection(eligible, state.current_weights)
        session.flush()
        return selected_name
