"""`codex_usage_api` + `xai_billing_credits` readers (todo 2872 sub-task 3):
direct HTTP reads of the two providers' subscription usage, using the
vendor CLI's own grant (read through by `_refresh.ensure_access_token`).

Response shapes below are LIVE-VERIFIED (todo 2872, 2026-07-30, against a
real Claude Max + Codex Pro + xAI account) -- both diverge from the plan's
reverse-engineered guesses, which came from decompiled binary strings for
xAI and an assumed `rate_limits[]`/`window_minutes` shape for Codex (there
never was a live token to check either against before). Parsed defensively
regardless: any shape this module doesn't recognize normalizes to
`parse_failed`, never a fabricated percent -- the house rule from
`storage.service.model_usage_limits` (malformed input must never masquerade
as a real number).

The xAI billing payload drifted again (todo 3001, 2026-08-03): the plain
`GET /v1/billing` view stopped needing a `format` param to carry usable
numbers and the account's `?format=credits` view stopped carrying
`creditUsagePercent`. The xAI reader now tries the plain view first (an
explicit `used`/`monthlyLimit` ratio) and only falls back to
`?format=credits` (the legacy `creditUsagePercent` shape) when the plain
view yields no usable window -- see `read_xai_provider` / `_parse_xai_window`.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import httpx

from . import _credentials as store
from ._errors import CredentialsMissingError, ReauthRequiredError
from ._refresh import ensure_access_token

_TIMEOUT_SECONDS = 15.0

ERROR_NOT_LOGGED_IN = "not_logged_in"
ERROR_REAUTH_REQUIRED = "reauth_required"
ERROR_PARSE_FAILED = "parse_failed"
ERROR_TRANSPORT = "transport_error"

# --- OpenAI / Codex ---------------------------------------------------------

CODEX_USAGE_URL = "https://chatgpt.com/backend-api/codex/usage"
CODEX_USER_AGENT = "codex_cli_rs/0.139.0"
CODEX_SOURCE = "codex_usage_api"

# Live shape: {"rate_limit": {"primary_window": {...}, "secondary_window":
# {...}|null}, ...}, each window carrying `used_percent`, `limit_window_seconds`
# and a unix-epoch `reset_at` -- NOT the plan's assumed `rate_limits[]` array
# keyed by `window_minutes` with an ISO `resets_at`. Key on the window's own
# `limit_window_seconds`, never on primary/secondary position: a live sample
# had the one-week window as `primary` and `secondary_window: null`, so
# "primary" is not reliably the shorter window.
_CODEX_WINDOW_SECONDS = {18000: "five_hour", 604800: "one_week"}

# --- xAI / Grok --------------------------------------------------------------

# The plain view (no `format` param) carries an explicit used/monthlyLimit
# quota and is requested first; `?format=credits` is a fallback for the
# legacy `creditUsagePercent` shape (todo 3001 -- xAI dropped that field from
# the plain view's steady-state payload, so the credits view no longer wins
# in practice, but is kept for self-healing if the reverse happens instead).
XAI_BILLING_URL = "https://cli-chat-proxy.grok.com/v1/billing"
XAI_BILLING_CREDITS_URL = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
XAI_CLIENT_VERSION = "0.2.101"
XAI_CLIENT_MODE = "cli"
XAI_SOURCE = "xai_billing_credits"


def _row(*, backend, provider, source, error, availability, windows, extra_windows,
         observed_at, account_id=None, account_name=None) -> dict:
    return {
        "backend": backend,
        "provider": provider,
        "account_id": account_id,
        "account_name": account_name,
        "observed_at": observed_at,
        "source": source,
        "availability": availability,
        "error": error,
        "windows": windows,
        "extra_windows": extra_windows,
    }


def read_codex_provider() -> dict:
    """`GET /backend-api/codex/usage` -> five_hour/one_week windows keyed on
    `window_minutes` (never on array order/position)."""
    observed_at = store.now_iso()
    try:
        access_token = ensure_access_token("openai")
    except CredentialsMissingError:
        return _row(backend="codex", provider="openai", source=CODEX_SOURCE,
                    error=ERROR_NOT_LOGGED_IN, availability="unavailable",
                    windows={}, extra_windows={}, observed_at=observed_at)
    except ReauthRequiredError:
        return _row(backend="codex", provider="openai", source=CODEX_SOURCE,
                    error=ERROR_REAUTH_REQUIRED, availability=ERROR_REAUTH_REQUIRED,
                    windows={}, extra_windows={}, observed_at=observed_at)

    grant = store.read_grant("openai") or {}
    account_id = (grant.get("extra") or {}).get("chatgpt_account_id")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": CODEX_USER_AGENT,
        "originator": "codex_cli_rs",
        "Accept": "application/json",
    }
    if account_id:
        headers["chatgpt-account-id"] = account_id

    try:
        resp = httpx.get(CODEX_USAGE_URL, headers=headers, timeout=_TIMEOUT_SECONDS)
    except httpx.HTTPError:
        return _row(backend="codex", provider="openai", source=CODEX_SOURCE,
                    error=ERROR_TRANSPORT, availability="unavailable",
                    windows={}, extra_windows={}, observed_at=observed_at, account_id=account_id)

    if resp.status_code == 401:
        return _row(backend="codex", provider="openai", source=CODEX_SOURCE,
                    error=ERROR_REAUTH_REQUIRED, availability=ERROR_REAUTH_REQUIRED,
                    windows={}, extra_windows={}, observed_at=observed_at, account_id=account_id)
    if resp.status_code >= 400:
        return _row(backend="codex", provider="openai", source=CODEX_SOURCE,
                    error=ERROR_TRANSPORT, availability="unavailable",
                    windows={}, extra_windows={}, observed_at=observed_at, account_id=account_id)

    try:
        body = resp.json()
    except ValueError:
        return _row(backend="codex", provider="openai", source=CODEX_SOURCE,
                    error=ERROR_PARSE_FAILED, availability="unavailable",
                    windows={}, extra_windows={}, observed_at=observed_at, account_id=account_id)

    windows = _parse_codex_windows(body)
    if not windows:
        return _row(backend="codex", provider="openai", source=CODEX_SOURCE,
                    error=ERROR_PARSE_FAILED, availability="unavailable",
                    windows={}, extra_windows={}, observed_at=observed_at, account_id=account_id)

    return _row(backend="codex", provider="openai", source=CODEX_SOURCE,
                error=None, availability="available",
                windows=windows, extra_windows={}, observed_at=observed_at, account_id=account_id)


def _parse_codex_windows(body: dict) -> dict:
    if not isinstance(body, dict):
        return {}
    rate_limit = body.get("rate_limit")
    if not isinstance(rate_limit, dict):
        return {}
    windows: dict = {}
    for key in ("primary_window", "secondary_window"):
        entry = rate_limit.get(key)
        if not isinstance(entry, dict):
            continue
        kind = _CODEX_WINDOW_SECONDS.get(entry.get("limit_window_seconds"))
        if not kind:
            continue
        windows[kind] = {
            "used_percent": entry.get("used_percent"),
            "reset_at": _unix_to_iso(entry.get("reset_at")),
        }
    return windows


def _unix_to_iso(ts) -> str | None:
    if not isinstance(ts, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def read_xai_provider() -> dict:
    """`GET /v1/billing` -> a single `billing_period` window (a usage
    percentage over a billing period, not a rolling 5h/1w window -- see the
    plan's per-provider verdict). Requests the plain view first (today's
    steady state: explicit `used`/`monthlyLimit`, no `creditUsagePercent`);
    only on a window-less parse does it fall back to `?format=credits` (the
    legacy shape, kept for self-healing -- see todo 3001)."""
    observed_at = store.now_iso()
    try:
        access_token = ensure_access_token("xai")
    except CredentialsMissingError:
        return _row(backend="grok", provider="xai", source=XAI_SOURCE,
                    error=ERROR_NOT_LOGGED_IN, availability="unavailable",
                    windows={}, extra_windows={}, observed_at=observed_at)
    except ReauthRequiredError:
        return _row(backend="grok", provider="xai", source=XAI_SOURCE,
                    error=ERROR_REAUTH_REQUIRED, availability=ERROR_REAUTH_REQUIRED,
                    windows={}, extra_windows={}, observed_at=observed_at)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-grok-client-version": XAI_CLIENT_VERSION,
        "x-grok-client-mode": XAI_CLIENT_MODE,
    }

    for url in (XAI_BILLING_URL, XAI_BILLING_CREDITS_URL):
        try:
            resp = httpx.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)
        except httpx.HTTPError:
            return _row(backend="grok", provider="xai", source=XAI_SOURCE,
                        error=ERROR_TRANSPORT, availability="unavailable",
                        windows={}, extra_windows={}, observed_at=observed_at)

        if resp.status_code == 401:
            return _row(backend="grok", provider="xai", source=XAI_SOURCE,
                        error=ERROR_REAUTH_REQUIRED, availability=ERROR_REAUTH_REQUIRED,
                        windows={}, extra_windows={}, observed_at=observed_at)
        if resp.status_code >= 400:
            return _row(backend="grok", provider="xai", source=XAI_SOURCE,
                        error=ERROR_TRANSPORT, availability="unavailable",
                        windows={}, extra_windows={}, observed_at=observed_at)

        try:
            body = resp.json()
        except ValueError:
            continue

        window = _parse_xai_window(body)
        if window is not None:
            return _row(backend="grok", provider="xai", source=XAI_SOURCE,
                        error=None, availability="available",
                        windows={"billing_period": window}, extra_windows={}, observed_at=observed_at)

    return _row(backend="grok", provider="xai", source=XAI_SOURCE,
                error=ERROR_PARSE_FAILED, availability="unavailable",
                windows={}, extra_windows={}, observed_at=observed_at)


def _parse_xai_window(body) -> dict | None:
    """Live shape: everything nests under `config`, not the top level.
    `creditUsagePercent` (the legacy `?format=credits` shape) is used
    directly when present; otherwise the percent is derived from the plain
    view's `used.val` / `monthlyLimit.val` (todo 3001 -- xAI stopped sending
    `creditUsagePercent` in the plain payload). `prepaidBalance` /
    `onDemandCap` / `onDemandUsed` / `used` / `monthlyLimit` are all
    `{"val": <number>}` objects, not raw numbers; the period-end field is
    `config.billingPeriodEnd` (ISO8601)."""
    if not isinstance(body, dict):
        return None
    config = body.get("config")
    if not isinstance(config, dict):
        return None
    used_percent = config.get("creditUsagePercent")
    if used_percent is None:
        used_percent = _derive_xai_used_percent(config)
    if used_percent is None:
        return None

    reset_at = config.get("billingPeriodEnd")
    if isinstance(reset_at, str):
        reset_at = reset_at.replace("+00:00", "Z")
    else:
        reset_at = None

    window: dict = {"used_percent": used_percent, "reset_at": reset_at}
    extra = {}
    for key in ("prepaidBalance", "onDemandCap", "onDemandUsed", "used", "monthlyLimit"):
        value = config.get(key)
        if isinstance(value, dict) and value.get("val") is not None:
            extra[key] = value["val"]
    if config.get("isUnifiedBillingUser") is not None:
        extra["isUnifiedBillingUser"] = config["isUnifiedBillingUser"]
    if extra:
        window["extra"] = extra
    return window


def _derive_xai_used_percent(config: dict) -> float | None:
    """`used.val / monthlyLimit.val * 100`, only when both are finite
    numbers and the denominator is positive -- never fabricate a percent
    from a missing or zero limit (the house rule from
    `storage.service.model_usage_limits._valid_percent`, enforced here too)."""
    used = config.get("used")
    monthly_limit = config.get("monthlyLimit")
    if not isinstance(used, dict) or not isinstance(monthly_limit, dict):
        return None
    used_val = used.get("val")
    limit_val = monthly_limit.get("val")
    if isinstance(used_val, bool) or not isinstance(used_val, (int, float)):
        return None
    if isinstance(limit_val, bool) or not isinstance(limit_val, (int, float)):
        return None
    if not math.isfinite(used_val) or not math.isfinite(limit_val) or limit_val <= 0:
        return None
    return used_val / limit_val * 100
