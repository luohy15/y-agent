"""Per-user relay key: sealed storage, launch override, and maintainer provisioning.

Launch mode ``credential`` (default) replaces a relay bot's in-memory api_key.
``bot_key`` leaves the stored bot key untouched. The bot row is never rewritten.
"""

from __future__ import annotations

import os
from dataclasses import replace
from urllib.parse import quote, urlsplit

import httpx
from loguru import logger

from storage.repository import relay_credential as repo
from storage.repository.user import get_user_by_user_id
from storage.service import bot_config as bot_config_service
from storage.service import model_usage_daily as usage_service
from storage.service.user import get_live_public_user_id

DEFAULT_ORIGIN = "https://cc1.yovy.app"
TEMPLATE_NAME = "subscription"
GROUP_NAME = "yagent-per-user"
TEMPLATE_TAG = "subscription-template"
MODES = ("bot_key", "credential")


class RelayCredentialMissing(Exception):
    """A relay-routed launch has no sealed key for this user."""

    def __init__(self, origin: str = ""):
        self.origin = origin or ""
        where = f" at {self.origin}" if self.origin else ""
        super().__init__(
            "No relay credential is stored for this user"
            f"{where}. Ask the maintainer to provision one with `y relay credential provision`."
        )


class RelayCredentialExists(Exception):
    """An yagent-user key or local row already exists and rotate was not asked."""


class RelayProvisionError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def credential_mode() -> str:
    mode = os.getenv("Y_AGENT_RELAY_CREDENTIAL_MODE", "credential").strip() or "credential"
    if mode not in MODES:
        return "credential"
    return mode


def relay_origins() -> tuple[str, ...]:
    raw = os.getenv("Y_AGENT_RELAY_ORIGINS", DEFAULT_ORIGIN)
    origins = tuple(part.strip().rstrip("/") for part in raw.split(",") if part.strip())
    return origins or (DEFAULT_ORIGIN,)


def primary_origin() -> str:
    return relay_origins()[0]


def origin_of(base_url: str) -> str | None:
    if not (base_url or "").strip():
        return None
    parts = urlsplit(base_url.strip())
    if not parts.netloc:
        return None
    return f"{parts.scheme or 'https'}://{parts.netloc}".rstrip("/")


def is_relay_bot(bot) -> bool:
    origin = origin_of(getattr(bot, "base_url", "") or "")
    return origin is not None and origin in relay_origins()


def launch_base_url(bot_config, entry=None) -> str:
    """Selected connection entry, then the row mirror of entry 0."""
    if isinstance(entry, dict):
        selected = entry.get("base_url") or ""
        if str(selected).strip():
            return str(selected)
    return getattr(bot_config, "base_url", "") or ""


def is_relay_launch(bot_config, entry=None) -> bool:
    origin = origin_of(launch_base_url(bot_config, entry))
    return origin is not None and origin in relay_origins()


def key_name_for(public_user_id: str) -> str:
    name = f"yagent-user-{public_user_id}"
    if not public_user_id or len(name) > 100:
        raise RelayProvisionError("key_name_too_long")
    return name


def lookup(user_id: int, origin: str):
    row = repo.get_for_user_origin(user_id, origin)
    if row is None or not row.api_key:
        return None
    return row


def resolve_for_launch(user_id: int, bot_config, entry=None):
    """Return a launch config. The selected entry's origin decides the relay key.

    ``entry`` is the connection chosen for this turn. Its base_url wins over the
    row, which only mirrors entry 0. ``bot_key`` mode leaves the stored key.
    """
    if credential_mode() == "bot_key" or not is_relay_launch(bot_config, entry):
        return bot_config
    origin = origin_of(launch_base_url(bot_config, entry))
    row = lookup(user_id, origin or "")
    if row is None:
        raise RelayCredentialMissing(origin or "")
    return replace(bot_config, api_key=row.api_key)


def availability(user_id: int) -> dict:
    row = lookup(user_id, primary_origin())
    names = sorted({
        config.name
        for config in bot_config_service.list_configs(user_id)
        if config.name and not is_relay_bot(config)
    })
    body = {
        "status": "available" if row else "unavailable",
        "non_relay_bots": names,
        "legacy_shared_excluded": True,
    }
    if row is None:
        body["reason"] = "no_relay_credential"
    return body


def status_for(user_id: int, origin: str | None = None) -> dict:
    origin = _allowed_origin(origin)
    row = lookup(user_id, origin)
    if row is None:
        return {"configured": False, "relay_origin": origin}
    return row.public_dict()


def resolve_owner(caller_id: int, public_user_id: str | None) -> tuple[int, str]:
    if public_user_id:
        user = get_user_by_user_id(public_user_id)
        if user is None:
            raise RelayProvisionError("user_missing")
        return user.id, user.user_id
    public = get_live_public_user_id(caller_id)
    if not public:
        raise RelayProvisionError("user_missing")
    return caller_id, public


def store_key(
    user_id: int,
    public_user_id: str,
    api_key: str,
    *,
    origin: str | None = None,
    relay_key_id: str = "",
    billing_mode: str | None = None,
    key_name: str | None = None,
) -> dict:
    if not api_key or not api_key.strip():
        raise RelayProvisionError("api_key_required")
    origin = _allowed_origin(origin)
    mode = billing_mode if billing_mode in {"real", "notional"} else "real"
    stored = repo.upsert(
        user_id,
        origin,
        api_key.strip(),
        relay_key_id=relay_key_id or "",
        key_name=key_name or key_name_for(public_user_id),
        billing_mode=mode,
    )
    return stored.public_dict()


def provision(
    caller_id: int,
    public_user_id: str | None = None,
    *,
    rotate: bool = False,
    origin: str | None = None,
) -> dict:
    """Create one additive relay key from the subscription template and seal it."""
    user_id, public_id = resolve_owner(caller_id, public_user_id)
    origin = _allowed_origin(origin)
    name = key_name_for(public_id)
    existing = repo.get_for_user_origin(user_id, origin)
    creds = usage_service._crs_admin_creds(caller_id)
    token = usage_service.crs_admin_login(origin, creds["username"], creds["password"])
    remote = _find_key(origin, token, name)
    if not rotate and (existing is not None or remote is not None):
        raise RelayCredentialExists(name)
    template = _find_key(origin, token, TEMPLATE_NAME)
    if template is None:
        raise RelayProvisionError("relay_template_missing")
    group_id = _group_id(origin, token)
    created = _create_key(origin, token, _create_body(template, name, public_id, group_id))
    api_key = created.get("apiKey") or ""
    if not api_key:
        raise RelayProvisionError("relay_request_failed")
    billing = _billing_mode(origin, api_key)
    stored = repo.upsert(
        user_id,
        origin,
        api_key,
        relay_key_id=str(created.get("id") or ""),
        key_name=name,
        billing_mode=billing,
    )
    retired = True
    previous = existing.relay_key_id if existing else ""
    if rotate and previous and previous != stored.relay_key_id:
        retired = _retire_key(origin, token, previous)
    body = stored.public_dict()
    body["previous_key_retired"] = retired
    return body


def _allowed_origin(origin: str | None) -> str:
    chosen = (origin or primary_origin()).rstrip("/")
    if chosen not in relay_origins():
        raise RelayProvisionError("origin_not_allowed")
    return chosen


def _create_body(template: dict, name: str, public_user_id: str, group_id: str) -> dict:
    console = template.get("claudeConsoleAccountId") or ""
    tag = f"yagent-user-{public_user_id}"
    tags = [TEMPLATE_TAG]
    if len(tag) <= 100:
        tags.append(tag)
    return {
        "name": name,
        "description": public_user_id[:500],
        "tokenLimit": 0,
        "concurrencyLimit": 0,
        "dailyCostLimit": 0,
        "totalCostLimit": 0,
        "weeklyOpusCostLimit": 0,
        "permissions": [],
        "enableModelRestriction": False,
        "restrictedModels": [],
        "enableClientRestriction": False,
        "allowedClients": [],
        "enableOpenAIResponsesCodexAdaptation": True,
        "claudeConsoleAccountId": console,
        "openaiAccountId": f"group:{group_id}",
        "tags": tags,
    }


def _billing_mode(origin: str, api_key: str) -> str:
    try:
        response = httpx.get(
            f"{origin}/openai/key-info",
            headers={"x-api-key": api_key, "User-Agent": usage_service._BROWSER_UA},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json() if response.content else {}
    except Exception as exc:
        logger.warning("relay credential key-info failed for {}: {}", origin, type(exc).__name__)
        return "notional"
    mode = str((payload or {}).get("billing_mode") or "").strip().lower()
    if mode in {"notional", "real"}:
        return mode
    return "notional"


def _find_key(origin: str, token: str, name: str) -> dict | None:
    page = 1
    pages = 1
    while page <= pages:
        path = (
            "/admin/api-keys?searchMode=apiKey&pageSize=100"
            f"&page={page}&search={quote(name)}"
        )
        payload = usage_service.crs_admin_get(origin, path, token)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise RelayProvisionError("relay_request_failed")
        for item in data.get("items") or []:
            if isinstance(item, dict) and item.get("name") == name:
                return item
        pagination = data.get("pagination") or {}
        pages = int(pagination.get("totalPages") or 1)
        page += 1
    return None


def _group_id(origin: str, token: str) -> str:
    payload = usage_service.crs_admin_get(origin, "/admin/account-groups", token)
    groups = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(groups, list):
        raise RelayProvisionError("relay_group_missing")
    matches = [
        group for group in groups
        if isinstance(group, dict) and group.get("name") == GROUP_NAME and group.get("id")
    ]
    if len(matches) != 1:
        raise RelayProvisionError("relay_group_missing")
    return str(matches[0]["id"])


def _create_key(origin: str, token: str, body: dict) -> dict:
    try:
        response = httpx.post(
            f"{origin}/admin/api-keys",
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": usage_service._BROWSER_UA,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning("relay credential create failed for {}: {}", origin, type(exc).__name__)
        raise RelayProvisionError("relay_request_failed") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise RelayProvisionError("relay_request_failed")
    return data


def _retire_key(origin: str, token: str, key_id: str) -> bool:
    try:
        response = httpx.delete(
            f"{origin}/admin/api-keys/{quote(key_id)}",
            headers={"Authorization": f"Bearer {token}", "User-Agent": usage_service._BROWSER_UA},
            timeout=30,
        )
        response.raise_for_status()
    except Exception as exc:
        logger.warning("relay credential retire failed for {}: {}", origin, type(exc).__name__)
        return False
    return True
