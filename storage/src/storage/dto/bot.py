import hashlib
import math
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

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
    backends: Optional[List[Dict]] = None
    model: str = ""
    description: Optional[str] = None
    openrouter_config: Optional[Dict] = None
    prompts: Optional[List[str]] = None
    max_tokens: Optional[int] = None
    resume_context_limit: Optional[int] = None
    custom_api_path: Optional[str] = None
    tier: Optional[str] = None
    tiers: Optional[Dict[str, Optional[float]]] = None
    type: Optional[str] = None
    route_weight: Optional[float] = None
    subscription_tiers: Optional[Dict[str, Optional[float]]] = None
    enabled: bool = True
    ref_bot_name: Optional[str] = None
    sub_ref_bot_name: Optional[str] = None
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


def normalize_tier_weights(tiers: Optional[Dict[str, Optional[float]]], tier: Optional[str] = None,
                           route_weight: Optional[float] = None) -> Dict[str, Optional[float]]:
    """Validate a full write, accepting legacy single-tier input when omitted."""
    values = tiers if tiers is not None else {tier or "tier3": route_weight}
    if not isinstance(values, dict) or not values or any(key not in TIERS for key in values):
        raise ValueError("tiers must be a nonempty map of tier0, tier1, tier2, tier3")
    for weight in values.values():
        if weight is not None and (
            isinstance(weight, bool) or not isinstance(weight, (int, float))
            or weight < 0 or not math.isfinite(weight)
        ):
            raise ValueError("tier weights must be finite nonnegative numbers or null")
    return dict(sorted(values.items()))


def tier_weights_of(config) -> Dict[str, Optional[float]]:
    """Read malformed/legacy rows safely and detect either legacy mirror drifting."""
    try:
        normalized = normalize_tier_weights(getattr(config, "tiers", None))
        strongest = next(iter(normalized))
        if strongest == config.tier and normalized[strongest] == config.route_weight:
            return normalized
    except (ValueError, TypeError, OverflowError):
        pass
    tier = config.tier if config.tier in TIERS else "tier3"
    return {tier: config.route_weight}


def subscription_tiers_of(config) -> Optional[Dict[str, Optional[float]]]:
    tiers = getattr(config, "subscription_tiers", None)
    if tiers is None:
        return None
    try:
        return normalize_tier_weights(tiers)
    except (ValueError, TypeError, OverflowError):
        return None


def tiers_of(config) -> List[str]:
    return list(tier_weights_of(config))


AGENTIC_BACKENDS = ("claude_code", "codex")
_ENTRY_KEYS = {"backend", "base_url", "model"}


def _row_backend(config) -> str:
    return getattr(config, "backend", None) or getattr(config, "api_type", None) or "claude_code"


def _row_entry(config) -> dict:
    entry = {"backend": _row_backend(config), "base_url": (getattr(config, "base_url", None) or "").strip()}
    model = (getattr(config, "model", None) or "").strip()
    if model:
        entry["model"] = model
    return entry


def _parse_entries(value, *, strict: bool, row_model: str = "") -> Optional[List[dict]]:
    try:
        if not isinstance(value, list) or not 1 <= len(value) <= 2:
            raise ValueError("backends must be 1 or 2 connection entries")
        cleaned = []
        seen = set()
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise ValueError("backends entries must be objects")
            unknown = set(item) - _ENTRY_KEYS
            if unknown:
                raise ValueError(f"unknown key {sorted(unknown)[0]}")
            backend = item.get("backend")
            base_url = item.get("base_url")
            model = item.get("model")
            if not isinstance(backend, str) or backend not in AGENTIC_BACKENDS:
                raise ValueError("backend must be claude_code or codex")
            if backend in seen:
                raise ValueError(f"duplicate backend {backend}")
            if not isinstance(base_url, str) or not base_url.strip():
                raise ValueError("base_url is required")
            if model is not None and (not isinstance(model, str) or not model.strip()):
                raise ValueError("model must be non-empty when set")
            seen.add(backend)
            entry = {"backend": backend, "base_url": base_url.strip()}
            if isinstance(model, str) and model.strip():
                entry["model"] = model.strip()
            elif index == 0 and row_model:
                entry["model"] = row_model
            cleaned.append(entry)
        return cleaned
    except ValueError:
        if strict:
            raise
        return None


def normalize_backends(backends, *, backend: Optional[str] = None, api_type: Optional[str] = None,
                       base_url: Optional[str] = None, model: Optional[str] = None):
    """Validate a write. Returns ``(array or None, backend, base_url, model)``.

    A missing array leaves the row columns as the single derived entry. A
    present array mirrors entry 0 into those columns. Inline bots cannot set
    an array. Malformed stored rows are repaired by ``backend_entries_of``.
    """
    preferred = backend or api_type or "claude_code"
    row_base = (base_url or "").strip()
    row_model = (model or "").strip()
    if backends is None:
        return None, preferred, row_base, row_model
    if preferred not in AGENTIC_BACKENDS:
        raise ValueError("inline backends cannot set backends")
    cleaned = _parse_entries(backends, strict=True, row_model=row_model)
    first = cleaned[0]
    return cleaned, first["backend"], first["base_url"], first.get("model") or ""


def stored_backends_of(config) -> Optional[List[dict]]:
    """The valid stored array, or None when the row columns are the single entry."""
    stored = getattr(config, "backends", None)
    if stored is None or _row_backend(config) not in AGENTIC_BACKENDS:
        return None
    return _parse_entries(stored, strict=False)


def backend_entries_of(config) -> List[dict]:
    """Stored array when valid, otherwise one entry derived from the row columns."""
    return stored_backends_of(config) or [_row_entry(config)]


def preferred_backend(config) -> str:
    """Entry 0. A NULL array uses the row backend, and both NULL means claude_code."""
    return backend_entries_of(config)[0]["backend"]


def entry_names(config) -> List[str]:
    return [entry["backend"] for entry in backend_entries_of(config)]


def has_codex_entry(config) -> bool:
    return "codex" in entry_names(config)


def entry_for(config, backend: str) -> dict:
    """The connection entry for ``backend``. A miss lists the bot's entries."""
    entries = backend_entries_of(config)
    for entry in entries:
        if entry["backend"] == backend:
            if entry.get("model"):
                return dict(entry)
            model = (getattr(config, "model", None) or "").strip()
            if model:
                return {**entry, "model": model}
            return dict(entry)
    from agent.config import BackendMismatchError
    raise BackendMismatchError(
        bot_name=getattr(config, "name", None),
        chat_backend=backend,
        entries=entries,
    )


def tier_weight(config, tier: str) -> Optional[float]:
    return tier_weights_of(config).get(tier)


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


# Known providers ignore the stored path. Relay is a cr_ key, not a host.
# An empty mount means the bare origin.
_PROVIDER_PATHS = {
    "relay": {"claude_code": "/api", "codex": "/openai", "openai": "/api/v1"},
    "api.deepseek.com": {"claude_code": "/anthropic", "codex": "", "openai": ""},
    "openrouter.ai": {"claude_code": "/api", "codex": "/api/v1", "openai": "/api/v1"},
}


def _provider_paths(base_url: str, api_key: Optional[str]) -> Optional[Dict[str, str]]:
    if (api_key or "").strip().startswith("cr_"):
        return _PROVIDER_PATHS["relay"]
    host = (urlsplit(base_url).hostname or "").lower()
    return _PROVIDER_PATHS.get(host)


def provider_base_url(base_url: Optional[str], backend: Optional[str], api_key: Optional[str] = None) -> str:
    """Protocol base for one entry. Unknown host or backend stays unchanged.

    An empty URL stays empty. A known provider, or a relay ``cr_`` key, replaces
    any stored path with the canonical mount for ``backend``.
    """
    raw = (base_url or "").strip()
    if not raw:
        return ""
    paths = _provider_paths(raw, api_key)
    if paths is None or backend not in paths:
        return raw
    parts = urlsplit(raw)
    if not parts.scheme or not parts.hostname:
        return raw
    return urlunsplit((parts.scheme, parts.netloc, paths[backend], "", "")).rstrip("/")


def _throughput_enabled(bot_config) -> bool:
    """True when the effective OpenRouter config selects providers by throughput."""
    config = effective_openrouter_config(bot_config)
    if not config:
        return False
    provider = config.get("provider", config)
    if not isinstance(provider, dict):
        return False
    return provider.get("sort") == "throughput"
