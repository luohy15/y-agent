"""`codex_usage_api` + `xai_billing_credits` readers (todo 2872 sub-task 3):
direct HTTP reads of the two providers' subscription usage, using the
y-agent-owned grant refreshed by `_refresh.ensure_access_token`.

Response shapes below are LIVE-VERIFIED (todo 2872, 2026-07-30, against a
real Claude Max + Codex Pro + xAI account) -- both diverge from the plan's
reverse-engineered guesses, which came from decompiled binary strings for
xAI and an assumed `rate_limits[]`/`window_minutes` shape for Codex (there
never was a live token to check either against before). Parsed defensively
regardless: any shape this module doesn't recognize normalizes to
`parse_failed`, never a fabricated percent -- the house rule from
`storage.service.model_usage_limits` (malformed input must never masquerade
as a real number).
"""

from __future__ import annotations

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

XAI_BILLING_URL = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
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

    record = store.get_record("openai") or {}
    account_id = (record.get("extra") or {}).get("chatgpt_account_id")
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
    """`GET /v1/billing?format=credits` -> a single `billing_period` window
    (a credit-usage percentage over a billing period, not a rolling
    5h/1w window -- see the plan's per-provider verdict)."""
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
    try:
        resp = httpx.get(XAI_BILLING_URL, headers=headers, timeout=_TIMEOUT_SECONDS)
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
        return _row(backend="grok", provider="xai", source=XAI_SOURCE,
                    error=ERROR_PARSE_FAILED, availability="unavailable",
                    windows={}, extra_windows={}, observed_at=observed_at)

    window = _parse_xai_window(body)
    if window is None:
        return _row(backend="grok", provider="xai", source=XAI_SOURCE,
                    error=ERROR_PARSE_FAILED, availability="unavailable",
                    windows={}, extra_windows={}, observed_at=observed_at)

    return _row(backend="grok", provider="xai", source=XAI_SOURCE,
                error=None, availability="available",
                windows={"billing_period": window}, extra_windows={}, observed_at=observed_at)


def _parse_xai_window(body) -> dict | None:
    """Live shape: everything nests under `config`, not the top level, and
    the plan's documented field list (decompiled from binary strings) was
    wrong in several places -- there is no top-level `creditUsagePercent` /
    `monthlyLimit`; `prepaidBalance` / `onDemandCap` / `onDemandUsed` are
    `{"val": <number>}` objects, not raw numbers; and the real period-end
    field is `config.billingPeriodEnd` (ISO8601), which the plan's list
    didn't include at all."""
    if not isinstance(body, dict):
        return None
    config = body.get("config")
    if not isinstance(config, dict):
        return None
    used_percent = config.get("creditUsagePercent")
    if used_percent is None:
        return None

    reset_at = config.get("billingPeriodEnd")
    if isinstance(reset_at, str):
        reset_at = reset_at.replace("+00:00", "Z")
    else:
        reset_at = None

    window: dict = {"used_percent": used_percent, "reset_at": reset_at}
    extra = {}
    for key in ("prepaidBalance", "onDemandCap", "onDemandUsed"):
        value = config.get(key)
        if isinstance(value, dict) and value.get("val") is not None:
            extra[key] = value["val"]
    if config.get("isUnifiedBillingUser") is not None:
        extra["isUnifiedBillingUser"] = config["isUnifiedBillingUser"]
    if extra:
        window["extra"] = extra
    return window
