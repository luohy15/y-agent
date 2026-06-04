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
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    api_type: Optional[str] = None
    backend: Optional[str] = None
    model: str = ""
    description: Optional[str] = None
    openrouter_config: Optional[Dict] = None
    prompts: Optional[List[str]] = None
    max_tokens: Optional[int] = None
    custom_api_path: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'BotConfig':
        return cls(**data)

    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


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
