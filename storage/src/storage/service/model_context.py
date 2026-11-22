"""Resolve a Codex badge denominator from the model context-window table."""

from typing import Optional

import httpx

from storage.dto.bot import BotConfig, backend_entries_of
from storage.repository import bot_config as bot_repo
from storage.repository import model_context_window as window_repo


def normalize_model_name(model) -> Optional[str]:
    """Exact model id after stripping spaces and wrapping double quotes."""
    if not isinstance(model, str):
        return None
    name = model.strip().strip('"').strip()
    return name or None


def get_context_window(model) -> Optional[int]:
    """Window for a resolved model, or None when it has no row.

    A query error propagates. The caller keeps the stored window in that case.
    """
    name = normalize_model_name(model)
    if name is None:
        return None
    return window_repo.get_by_model(name)


def collect_models(configs: list[BotConfig]) -> list[str]:
    models = set()
    for config in configs:
        if config.enabled is False:
            continue
        for entry in backend_entries_of(config):
            name = normalize_model_name(entry.get("model") or config.model)
            if name:
                models.add(name)
    return sorted(models)


def parse_catalog(payload: dict) -> dict[str, int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("invalid OpenRouter catalog envelope")
    catalog = {}
    for entry in payload["data"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"]:
            raise ValueError("invalid OpenRouter catalog entry")
        provider = entry.get("top_provider")
        for length in (entry.get("context_length"), provider.get("context_length") if isinstance(provider, dict) else None):
            if type(length) is int and length > 0:
                catalog[entry["id"]] = length
                break
    return catalog


def fetch_catalog() -> dict[str, int]:
    response = httpx.get("https://openrouter.ai/api/v1/models", timeout=15)
    response.raise_for_status()
    return parse_catalog(response.json())


def match_catalog_id(model: str, catalog: dict[str, int]) -> tuple[str | None, str]:
    if model in catalog:
        return model, "exact"
    matches = [key for key in catalog if key.endswith("/" + model) and ":" not in key and not key.startswith("~")]
    if len(matches) == 1:
        return matches[0], "suffix"
    return None, "ambiguous" if matches else "no_match"


def sync_missing_windows() -> dict:
    models = collect_models(bot_repo.list_all_configs())
    missing = sorted(set(models) - window_repo.list_models())
    catalog = fetch_catalog() if missing else {}
    rows, absent = [], {}
    for model in missing:
        catalog_id, reason = match_catalog_id(model, catalog)
        if catalog_id is None:
            absent[model] = reason
        else:
            rows.append({"model": model, "context_window": catalog[catalog_id], "note": f"openrouter:{catalog_id}"})
    return {"models_checked": len(models), "inserted": window_repo.insert_missing(rows), "absent_from_catalog": absent}
