import hashlib
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

DEFAULT_OPENROUTER_CONFIG = {
    "provider": {
        "sort": "throughput"
    }
}

@dataclass
class BotConfig:
    name: str
    base_url: str = ""
    api_key: str = ""
    api_type: Optional[str] = None
    backend: Optional[str] = None
    model: str = ""
    description: Optional[str] = None
    openrouter_config: Optional[Dict] = None
    prompts: Optional[List[str]] = None
    max_tokens: Optional[int] = None
    resume_context_limit: Optional[int] = None
    custom_api_path: Optional[str] = None
    tier: Optional[str] = None
    tiers: Optional[List[str]] = None
    type: Optional[str] = None
    route_weight: Optional[float] = None
    enabled: bool = True
    ref_bot_name: Optional[str] = None
    effort_levels: Optional[List[str]] = None
    effort_evidence: Optional[str] = None
    effort_binding: Optional[str] = None

    @property
    def effort_stale(self) -> bool:
        return self.effort_levels is not None and self.effort_binding != effort_binding(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'BotConfig':
        return cls(**{k: v for k, v in data.items() if k != "effort_stale"})

    def to_dict(self) -> Dict:
        result = {}
        for k, v in asdict(self).items():
            # enabled is a boolean default True — always include it so the
            # receiver can tell explicit False from a missing key.
            if v is not None or k == "enabled":
                result[k] = v
        result["effort_stale"] = self.effort_stale
        return result


TIERS = ("tier0", "tier1", "tier2", "tier3")


def normalize_tiers(tiers: Optional[List[str]], tier: Optional[str] = None) -> List[str]:
    """Normalize a write, accepting the legacy single-tier input when omitted."""
    values = tiers if tiers is not None else [tier or "tier3"]
    if not isinstance(values, list) or not values or any(value not in TIERS for value in values):
        raise ValueError("tiers must be a nonempty list of tier0, tier1, tier2, tier3")
    return sorted(set(values))


def tiers_of(config) -> List[str]:
    """Read old rows and detect legacy writers that changed only the mirror."""
    tiers = getattr(config, "tiers", None)
    if tiers:
        normalized = normalize_tiers(tiers)
        if normalized[0] == config.tier:
            return normalized
    return normalize_tiers(None, config.tier)


EFFORT_LEVELS = frozenset({"low", "medium", "high", "xhigh", "max"})


def effort_binding(config) -> str:
    """Bind a declaration to provider identity, not credentials or routing weight."""
    identity = "|".join((
        config.backend or config.api_type or "",
        (config.model or "").strip(),
        (config.base_url or "").strip().rstrip("/"),
    ))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def effective_effort_levels(config) -> List[str]:
    if config.effort_binding != effort_binding(config):
        return []
    return config.effort_levels or []


def _is_openrouter_routed(bot_config) -> bool:
    """Whether a bot's requests are ultimately routed to OpenRouter.

    Covers both the stock OpenRouter endpoint and the Cloudflare AI Gateway
    passthrough (base_url ending in `/openrouter`, api_key `sk-or-...`).
    """
    base_url = (getattr(bot_config, "base_url", None) or "").strip().rstrip("/")
    api_key = (getattr(bot_config, "api_key", None) or "").strip()
    return base_url.endswith("/openrouter") or api_key.startswith("sk-or-")


def effective_openrouter_config(bot_config) -> Optional[Dict]:
    """The bot's explicit openrouter_config, else the throughput default for
    OpenRouter-routed bots (so every OpenRouter bot defaults to throughput while
    keeping a per-bot override). Returns None when neither applies."""
    explicit = getattr(bot_config, "openrouter_config", None)
    if explicit:
        return explicit
    if _is_openrouter_routed(bot_config):
        return DEFAULT_OPENROUTER_CONFIG
    return None


def _throughput_enabled(bot_config) -> bool:
    """True when the effective OpenRouter config selects providers by throughput."""
    config = effective_openrouter_config(bot_config)
    if not config:
        return False
    provider = config.get("provider", config)
    if not isinstance(provider, dict):
        return False
    return provider.get("sort") == "throughput"
