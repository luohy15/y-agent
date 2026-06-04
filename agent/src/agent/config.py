"""Shared configuration helpers for CLI and worker."""

import logging
import os
import random
from typing import Dict, List, Optional, Tuple

from storage.entity.dto import BotConfig, VmConfig
from storage.service import bot_config as bot_service
from storage.service import bot_pricing
from storage.service import vm_config as vm_service
from storage.service.user import get_default_user_id

logger = logging.getLogger(__name__)

# Fallback prices for weighting when a bot's OpenRouter price is unknown.
# Used by tier1/tier2 inverse-square routing. tier0 uses uniform random.
TIER_FALLBACK_PRICES: Dict[str, float] = {
    "tier0": 10.0,
    "tier1": 5.0,
    "tier2": 1.0,
}

# Phase 0 static skill->tier mapping.
# Unlisted skills (and *all* new skills) default to tier1 (conservative).
# tier2 is an explicit allowlist of cheap-safe skills only.
# tier0 set is EMPTY: no skill auto-routes to tier0 (opt-in via --bot / --tier only).
SKILL_TO_TIER: Dict[str, str] = {
    "artifact": "tier2",
    "calendar": "tier2",
    "cdn": "tier2",
    "chat": "tier2",
    "daily-changelog": "tier2",
    "deploy": "tier2",
    "email-style": "tier2",
    "entity": "tier2",
    "exit-watch": "tier2",
    "finance": "tier2",
    "finance-changelog": "tier2",
    "format-zh": "tier2",
    "git": "tier2",
    "hr": "tier2",
    "image": "tier2",
    "journal": "tier2",
    "link": "tier2",
    "note": "tier2",
    "openrouter-credit-check": "tier2",
    "pdf": "tier2",
    "refine": "tier2",
    "reminder": "tier2",
    "style-zh": "tier2",
    "test": "tier2",
}


def _effective_backend(bot_config: BotConfig) -> str:
    return bot_config.backend or bot_config.api_type


def _find_bot_config_by_backend(user_id: int, backend: str, bot_name: str = None) -> Optional[BotConfig]:
    configs = bot_service.list_configs(user_id)
    matches = [config for config in configs if _effective_backend(config) == backend]

    if bot_name:
        for config in matches:
            if config.name == bot_name:
                return config

    for preferred_name in (backend, "default"):
        for config in matches:
            if config.name == preferred_name and config.enabled:
                return config

    for config in matches:
        if config.enabled:
            return config
    return None


# --- Tier helpers ---

def tier_of(bot_config: BotConfig) -> str:
    """Return the tier for a bot config.

    Explicit bot_config.tier wins; NULL/unspecified defaults to tier1
    (conservative).
    """
    return bot_config.tier or "tier1"


def _bots_for_tier(user_id: int, tier: str, catalog: Optional[dict] = None) -> List[Tuple[BotConfig, Optional[float]]]:
    """Return list of (bot_config, input_price) for bots matching the tier.

    Excludes perplexity backend (px is pin-only, not a pool member).
    Excludes type='model' bots (inline, tldr, etc.) from auto-routing.
    Each bot queries its price exactly once.
    """
    if catalog is None:
        catalog = bot_pricing.fetch_openrouter_catalog()
    configs = bot_service.list_configs(user_id)
    bots = []
    for cfg in configs:
        effective = cfg.backend or cfg.api_type
        # Safety: keep perplexity hard-exclusion (belt + suspenders)
        if effective == "perplexity":
            continue
        type_val = getattr(cfg, "type", None) or "agent"
        if type_val == "model":
            continue
        if not cfg.enabled:
            continue
        if tier_of(cfg) == tier:
            input_price, _ = bot_pricing.bot_prices_per_1m(cfg, catalog)
            bots.append((cfg, input_price))
    return bots


def _pick_by_weight(bots_and_prices: List[Tuple[BotConfig, Optional[float]]], fallback_price: float) -> Optional[BotConfig]:
    """Weighted random pick from bots by inverse-square-of-price (w = 1/price^2).

    Cheapest bots are heavily favored.
    Price priority: price_override > OpenRouter catalog > fallback_price.
    """
    if not bots_and_prices:
        return None

    weights = []
    choices = []
    for cfg, price in bots_and_prices:
        if getattr(cfg, "price_override", None) is not None:
            effective_price = cfg.price_override
        elif price is not None:
            effective_price = price
        else:
            effective_price = fallback_price
        if effective_price <= 0:
            effective_price = fallback_price
        weight = 1.0 / (effective_price ** 2)
        weights.append(weight)
        choices.append(cfg)

    return random.choices(choices, weights=weights, k=1)[0]


def _pick_uniform(bots_and_prices: List[Tuple[BotConfig, Optional[float]]]) -> Optional[BotConfig]:
    """Uniform random pick (equal weight, retained but no longer used)."""
    if not bots_and_prices:
        return None
    return random.choice([b[0] for b in bots_and_prices])


def resolve_bot_config(user_id: int, bot_name: str = None, backend: str = None, tier: str = None) -> BotConfig:
    # Priority 1: backend pin
    if backend:
        bot_config = _find_bot_config_by_backend(user_id, backend, bot_name)
        if not bot_config:
            default_user_id = get_default_user_id()
            if default_user_id != user_id:
                bot_config = _find_bot_config_by_backend(default_user_id, backend, bot_name)
        if bot_config:
            return bot_config

        logger.warning(
            "No bot config found for user_id=%s bot_name=%s backend=%s; using backend-only fallback",
            user_id,
            bot_name,
            backend,
        )
        return BotConfig(name=bot_name or backend, backend=backend)

    # Priority 2: bot_name pin (original path, no cross-user fallback)
    bot_config = None
    if bot_name:
        bot_config = bot_service.get_config(user_id, bot_name)

    # Priority 3: tier-based selection (only when no explicit pin)
    if not bot_config and not bot_name and tier:
        catalog = bot_pricing.fetch_openrouter_catalog()
        bots_and_prices = _bots_for_tier(user_id, tier, catalog)
        if bots_and_prices:
            fallback = TIER_FALLBACK_PRICES.get(tier, 1.0)
            selected = _pick_by_weight(bots_and_prices, fallback)
            if selected:
                return selected
        logger.warning(
            "No qualified bots for tier %s (user_id=%s); falling back to default",
            tier,
            user_id,
        )

    # Fallback: default logic (original path preserved)
    if not bot_config:
        bot_config = bot_service.get_config(user_id)
    if not bot_config:
        default_user_id = get_default_user_id()
        if default_user_id != user_id:
            bot_config = bot_service.get_config(default_user_id)
    if not bot_config:
        raise ValueError(f"No bot config found for user_id={user_id}, bot_name={bot_name}")
    return bot_config


def resolve_vm_config(user_id: int, vm_name: str = None, work_dir: str = None) -> VmConfig:
    vm_config = None
    if vm_name:
        vm_config = vm_service.get_config(user_id, vm_name)
    if not vm_config and work_dir:
        vm_config = vm_service.get_config_by_work_dir(user_id, work_dir)
    if not vm_config:
        vm_config = vm_service.get_config(user_id, "default")
    if not vm_config:
        default_user_id = get_default_user_id()
        if default_user_id != user_id:
            vm_config = vm_service.get_config(default_user_id, "default")
    if not vm_config:
        vm_config = VmConfig()
        vm_config.work_dir = os.environ.get("VM_WORK_DIR_CLI", "")
    if work_dir:
        vm_config.work_dir = work_dir
    return vm_config
