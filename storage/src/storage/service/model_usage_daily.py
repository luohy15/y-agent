"""Provider-generic daily LLM usage: per-source pulls into one upsert table.

One source in scope:
- CRS (claude-relay-service): POST {origin}/apiStats/api/user-model-stats with each
  distinct cr_ relay key referenced by the user's bot_configs, period='daily' ->
  today's per-model tokens + real cost. The endpoint is strictly per-key, so we
  enumerate every distinct key and SUM per model to reconstruct the global per-model
  aggregate (cc1 is a single-user relay, so the sum equals CRS's own
  usage:model:daily:* global). Stored as scope='aggregate' rows (key enumeration is an
  invisible impl detail — no per-key rows). Today-only (no history); we pull daily.
"""

import os
from datetime import date, timedelta
from urllib.parse import urlsplit

import httpx
from loguru import logger

from storage.repository import model_usage_daily as repo
from storage.service import bot_config as bot_config_service
from storage.service import user_preference as user_pref_service
from storage.util import get_utc_iso8601_timestamp, local_today

# Cloudflare in front of CRS blocks the default urllib/httpx UA (error 1010).
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)


# --- thin storage passthroughs ---------------------------------------------

def upsert_daily(user_id: int, rows: list[dict], synced_at: str | None = None) -> int:
    return repo.upsert_daily(user_id, rows, synced_at or get_utc_iso8601_timestamp())


def list_for(user_id: int, source: str | None = None, from_date: str | None = None, to_date: str | None = None, limit: int = 1000):
    return repo.list_for(user_id, source=source, from_date=from_date, to_date=to_date, limit=limit)


def _heatmap_window(year: int | None) -> tuple[str, str]:
    """The contribution heatmap's date range, independent of the Live time filter:
    a specific 4-digit `year` spans that whole calendar year (Jan 1 -> Dec 31);
    otherwise the month-aligned past 12 months (the 1st of the month 11 months back
    through today). Mirrors BotViewer.buildHeatmapWeeks so the rows cover its grid."""
    if year is not None:
        return f"{year}-01-01", f"{year}-12-31"
    today = date.fromisoformat(_local_today())
    y, m = today.year, today.month - 11
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1).isoformat(), today.isoformat()


def daily_totals(user_id: int, year: int | None = None, source: str | None = "crs") -> list[dict]:
    """Per-day usage totals (tokens / cost / requests summed across all models) over
    the heatmap window, decoupled from the Live time-range filter. Drives the bot
    usage contribution heatmap so it always renders its full historical window."""
    from_date, to_date = _heatmap_window(year)
    rows = repo.list_for(user_id, source=source, from_date=from_date, to_date=to_date, limit=1000000)
    by_day: dict[str, dict] = {}
    for r in rows:
        agg = by_day.setdefault(r.usage_date, {"all_tokens": 0, "cost": 0.0, "requests": 0})
        agg["all_tokens"] += r.all_tokens or 0
        agg["cost"] += r.cost or 0.0
        agg["requests"] += r.requests or 0
    return [{"usage_date": d, **agg} for d, agg in sorted(by_day.items())]


# --- helpers ----------------------------------------------------------------

def _derive_provider(model: str) -> str:
    """Map a model id to its vendor. OpenRouter ids are 'vendor/model'; CRS ids
    are bare (e.g. 'claude-opus-4-8', 'gpt-5.5')."""
    if not model or model == "*":
        return ""
    if "/" in model:
        return model.split("/", 1)[0]
    m = model.lower()
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith(("gpt", "o1", "o3", "o4", "chatgpt")):
        return "openai"
    if m.startswith("gemini"):
        return "google"
    if m.startswith("grok"):
        return "x-ai"
    if m.startswith("glm"):
        return "z-ai"
    if m.startswith("deepseek"):
        return "deepseek"
    if m.startswith("qwen"):
        return "qwen"
    if m.startswith(("kimi", "moonshot")):
        return "moonshotai"
    if m.startswith("minimax"):
        return "minimax"
    return ""


def _local_today() -> str:
    """Today's date in the configured timezone (CRS stamps daily keys in its app
    TZ; we mirror Y_AGENT_TIMEZONE via storage.util.local_today(), the single
    source shared with the read-path fava day resolution — todo 2953)."""
    return local_today().isoformat()


# --- CRS pull ---------------------------------------------------------------

def _crs_targets(user_id: int) -> list[tuple[str, str]]:
    """Distinct CRS (origin, api_key) pairs across the user's bot_configs.

    Enumerates every cr_ key referenced by a bot_config and dedups by
    (origin, api_key) so a key shared by multiple bots (e.g. the subscription key
    used by claude_code + codex) is queried once. Self-maintaining: a new bot
    repointed to CRS is auto-discovered with no code change here. Enumeration is an
    invisible impl detail — the results are summed into one global aggregate."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for c in bot_config_service.list_configs(user_id):
        ak = c.api_key or ""
        if not ak.startswith("cr_"):
            continue
        parts = urlsplit(c.base_url or "https://cc1.yovy.app/api")
        origin = f"{parts.scheme or 'https'}://{parts.netloc}"
        target = (origin, ak)
        if target in seen:
            continue
        seen.add(target)
        out.append(target)
    return out


def _fetch_crs_key(origin: str, api_key: str) -> list[dict]:
    """Today's per-model items for one CRS key (raises on transport/HTTP error)."""
    resp = httpx.post(
        f"{origin}/apiStats/api/user-model-stats",
        json={"apiKey": api_key, "period": "daily"},
        headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data") or []


def _crs_key_basis(origin: str, api_key: str) -> str:
    """Whether a relay key rides a flat-fee subscription (`notional` list-price
    cost) or pay-per-token billing (`real`). The relay exposes each key's name
    at GET {origin}/openai/key-info; the y-agent subscription key is literally
    named `subscription`, so its list-price cost figure is notional, never
    dollars charged. Failures and any non-subscription name default to `real`
    (conservative: never downgrade a spend figure to notional on uncertainty)."""
    try:
        resp = httpx.get(
            f"{origin}/openai/key-info",
            headers={"x-api-key": api_key, "User-Agent": _BROWSER_UA},
            timeout=15,
        )
        resp.raise_for_status()
        name = (resp.json() or {}).get("name") or ""
    except Exception as e:
        logger.warning("_crs_key_basis: key-info failed for {}; assuming real: {}", origin, e)
        return "real"
    return "notional" if name.strip().lower() == "subscription" else "real"


def _aggregate_basis(bases: set[str]) -> str:
    """Roll a per-model set of contributing key bases into one label: `notional`
    only when every contributing key is subscription-backed, else `real` (a
    single pay-per-token key makes the sum a real spend figure)."""
    return "notional" if bases == {"notional"} else "real"


def sync_crs(user_id: int, synced_at: str | None = None) -> dict:
    """Pull today's per-model usage across all distinct CRS keys, SUM per model, and
    upsert as global source='crs' scope='aggregate' rows (one row per model)."""
    targets = _crs_targets(user_id)
    if not targets:
        return {"source": "crs", "status": "skip", "reason": "no cr_ keys in bot_configs", "rows": 0}

    # model -> summed totals across every distinct key (the global per-model aggregate).
    agg: dict[str, dict] = {}
    agg_basis: dict[str, set] = {}
    for origin, api_key in targets:
        basis = _crs_key_basis(origin, api_key)
        try:
            items = _fetch_crs_key(origin, api_key)
        except Exception as e:
            logger.exception("sync_crs: fetch failed for a key: {}", e)
            return {"source": "crs", "status": "error", "reason": str(e), "rows": 0}
        for item in items:
            model = item.get("model") or "*"
            costs = item.get("costs") or {}
            agg_basis.setdefault(model, set()).add(basis)
            row = agg.setdefault(model, {
                "input_tokens": 0, "output_tokens": 0, "cache_create_tokens": 0,
                "cache_read_tokens": 0, "all_tokens": 0, "requests": 0, "cost": 0.0,
            })
            row["input_tokens"] += item.get("inputTokens") or 0
            row["output_tokens"] += item.get("outputTokens") or 0
            row["cache_create_tokens"] += item.get("cacheCreateTokens") or 0
            row["cache_read_tokens"] += item.get("cacheReadTokens") or 0
            row["all_tokens"] += item.get("allTokens") or 0
            row["requests"] += item.get("requests") or 0
            row["cost"] += costs.get("real", costs.get("total", 0.0)) or 0.0

    usage_date = _local_today()
    rows = [{
        "usage_date": usage_date,
        "source": "crs",
        "provider": _derive_provider(model),
        "model": model,
        "scope": "aggregate",
        "scope_id": "",
        "scope_name": "",
        "cost_basis": _aggregate_basis(agg_basis[model]),
        **totals,
    } for model, totals in agg.items()]

    n = upsert_daily(user_id, rows, synced_at)
    logger.info("sync_crs: {} keys -> upserted {} aggregate rows for {}", len(targets), n, usage_date)
    return {"source": "crs", "status": "ok", "rows": n, "date": usage_date}


# --- CRS admin client (one-shot historical backfill) -----------------------
#
# The public per-key user-model-stats endpoint is today-only, so dated history
# is only reachable through the admin model-stats route (global daily buckets by
# date). Shared by the manual `backfill_crs` one-shot and the direct run-rate
# reader (`storage.service.usage_rate.read_rate`), which stores the admin
# credentials in `user_preference` under `crs_admin`.

def _crs_config_block() -> dict:
    """The optional [crs] table in ~/.y-agent/config.toml (nested tables are not
    loaded into env by global_config, so read it directly)."""
    path = os.path.join(os.path.expanduser("~/.y-agent"), "config.toml")
    if not os.path.exists(path):
        return {}
    import tomllib
    with open(path, "rb") as f:
        return tomllib.load(f).get("crs") or {}


def _crs_admin_creds(user_id: int | None = None) -> dict:
    """Admin credentials from the DB, then env or the local [crs] config block."""
    if user_id is not None:
        pref = user_pref_service.get_preference(user_id, "crs_admin")
        value = pref.value if pref and isinstance(pref.value, dict) else None
        if isinstance(value, dict) and isinstance(value.get("username"), str) and isinstance(value.get("password"), str):
            if value["username"] and value["password"]:
                return {"username": value["username"], "password": value["password"]}

    username = os.getenv("CRS_ADMIN_USERNAME")
    password = os.getenv("CRS_ADMIN_PASSWORD")
    if not (username and password):
        block = _crs_config_block()
        username = username or block.get("admin_username")
        password = password or block.get("admin_password")
    if not (username and password):
        raise RuntimeError(
            "CRS admin creds missing: set CRS_ADMIN_USERNAME/CRS_ADMIN_PASSWORD or a "
            "[crs] block (admin_username/admin_password) in ~/.y-agent/config.toml"
        )
    return {"username": username, "password": password}


def crs_admin_login(origin: str, username: str, password: str, timeout: float = 30) -> str:
    """POST {origin}/web/auth/login -> an admin session token."""
    resp = httpx.post(
        f"{origin}/web/auth/login",
        json={"username": username, "password": password},
        headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        timeout=timeout,
    )
    resp.raise_for_status()
    token = resp.json().get("token")
    if not token:
        raise RuntimeError("CRS admin login returned no token")
    return token


def crs_admin_get(origin: str, path: str, token: str, timeout: float = 60) -> dict:
    """GET an admin endpoint with the session token (Bearer)."""
    resp = httpx.get(
        f"{origin}{path}",
        headers={"Authorization": f"Bearer {token}", "User-Agent": _BROWSER_UA},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def _crs_origin(user_id: int) -> str:
    """Admin-endpoint origin: the user's first CRS bot_config origin, else cc1."""
    targets = _crs_targets(user_id)
    return targets[0][0] if targets else "https://cc1.yovy.app"


def backfill_crs(user_id: int, days: int = 32, synced_at: str | None = None) -> dict:
    """One-shot historical backfill via the CRS admin routes (manual, not the
    recurring worker). For each day in [today-days, yesterday] call
    GET /admin/model-stats?startDate=D&endDate=D and write scope='aggregate'/
    scope_id='' rows — the SAME shape as the go-forward daily sync, so re-running
    (or overlapping a go-forward day) upserts in place. Today is left to the
    go-forward sync (cap at yesterday). Only the dated daily window (~32d, the
    CRS daily-bucket TTL) is recoverable; older history has expired in Redis.

    Idempotent: every row reuses the existing unique key, so a re-run leaves the
    row count unchanged and refreshes counters in place. Because historical admin
    stats lack per-key attribution, backfill omits cost_basis: new rows default to
    `real`, while existing go-forward labels remain unchanged."""
    synced_at = synced_at or get_utc_iso8601_timestamp()
    creds = _crs_admin_creds(user_id)
    origin = _crs_origin(user_id)
    token = crs_admin_login(origin, creds["username"], creds["password"])

    result: dict = {"source": "crs", "status": "ok", "origin": origin, "daily_rows": 0, "days": []}

    # The admin endpoint has no per-key attribution, so backfill omits the basis.
    # New rows use the database's `real` default; conflicts preserve the existing
    # label rather than fabricating attribution or erasing go-forward knowledge.

    # dated daily window [today-days, yesterday] (caps at yesterday so the
    # go-forward sync keeps ownership of the in-progress day).
    today = date.fromisoformat(_local_today())
    daily_total = 0
    for i in range(days, 0, -1):
        d = (today - timedelta(days=i)).isoformat()
        data = crs_admin_get(origin, f"/admin/model-stats?startDate={d}&endDate={d}", token)
        items = data.get("data") or []
        if not items:
            continue
        rows = []
        for item in items:
            model = item.get("model") or "*"
            costs = item.get("costs") or {}
            rows.append({
                "usage_date": d,
                "source": "crs",
                "provider": _derive_provider(model),
                "model": model,
                "scope": "aggregate",
                "scope_id": "",
                "scope_name": "",
                "input_tokens": int(item.get("inputTokens") or 0),
                "output_tokens": int(item.get("outputTokens") or 0),
                "cache_create_tokens": int(item.get("cacheCreateTokens") or 0),
                "cache_read_tokens": int(item.get("cacheReadTokens") or 0),
                "all_tokens": int(item.get("allTokens") or 0),
                "requests": int(item.get("requests") or 0),
                "cost": float(costs.get("total") or 0.0),
            })
        daily_total += upsert_daily(user_id, rows, synced_at)
        result["days"].append({"date": d, "rows": len(rows)})
    result["daily_rows"] = daily_total

    logger.info(
        "backfill_crs: {} dated days ({} rows) from {}",
        len(result["days"]), result["daily_rows"], origin,
    )
    return result


# --- orchestration ----------------------------------------------------------

def sync(user_id: int, source: str | None = None) -> dict:
    """Run the enabled source pulls. `source` filters to one of crs."""
    synced_at = get_utc_iso8601_timestamp()
    results = []
    if source in (None, "crs"):
        results.append(sync_crs(user_id, synced_at))
    return {"status": "ok", "results": results}
