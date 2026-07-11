"""Bot route state service."""

from typing import List, Optional, Tuple

from storage.repository import bot_route_state as bot_route_state_repo


def select_weighted_round_robin(user_id: int, tier: str, candidates: List[Tuple[str, float]]) -> Optional[str]:
    return bot_route_state_repo.select_weighted_round_robin(user_id, tier, candidates)
