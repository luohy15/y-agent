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

import concurrent.futures
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

# Independent per-key CRS reads (basis lookups, daily/hourly stat pulls) run
# concurrently up to this bound, sharing one connection-pooled client per
# sync() call instead of one fresh connection per request (todo 3520).
_MAX_CONCURRENT_SOURCE_READS = 4


def new_http_client(timeout: float = 30) -> httpx.Client:
    """One pooled client for every CRS request in a sync() call (daily +
    hourly), reusing TCP/TLS connections per origin instead of dialing fresh
    for each of the historically ~15 sequential requests."""
    return httpx.Client(headers={"User-Agent": _BROWSER_UA}, timeout=timeout)


def _run_bounded(work: dict) -> dict:
    """Run each zero-arg callable in `work` (keyed by whatever the caller
    wants to look results up by) with bounded concurrency, returning a dict
    of the same keys to either the result or the raised exception (never
    re-raised here, so callers can apply their own fixed-order fail-fast
    policy after every independent read has settled)."""
    if not work:
        return {}
    max_workers = min(_MAX_CONCURRENT_SOURCE_READS, len(work))
    results: dict = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fn): key for key, fn in work.items()}
        for future, key in futures.items():
            try:
                results[key] = future.result()
            except Exception as e:  # noqa: BLE001 - surfaced to caller, not swallowed
                results[key] = e
    return results


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


def _fetch_crs_key(client: httpx.Client, origin: str, api_key: str) -> list[dict]:
    """Today's per-model items for one CRS key (raises on transport/HTTP error)."""
    resp = client.post(
        f"{origin}/apiStats/api/user-model-stats",
        json={"apiKey": api_key, "period": "daily"},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data") or []


def _crs_key_basis(client: httpx.Client, origin: str, api_key: str) -> str:
    """Whether a relay key rides a flat-fee subscription (`notional` list-price
    cost) or pay-per-token billing (`real`). The relay exposes each key's name
    at GET {origin}/openai/key-info; the y-agent subscription key is literally
    named `subscription`, so its list-price cost figure is notional, never
    dollars charged. Failures and any non-subscription name default to `real`
    (conservative: never downgrade a spend figure to notional on uncertainty)."""
    try:
        resp = client.get(
            f"{origin}/openai/key-info",
            headers={"x-api-key": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        name = (resp.json() or {}).get("name") or ""
    except Exception as e:
        logger.warning("_crs_key_basis: key-info failed for {}; assuming real: {}", origin, e)
        return "real"
    return "notional" if name.strip().lower() == "subscription" else "real"


def resolve_key_basis(client: httpx.Client, targets: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """One basis lookup per distinct (origin, api_key), bounded concurrency,
    computed once and shared across the daily + hourly grains of the same
    sync() call instead of each grain re-resolving every key's basis.
    `_crs_key_basis` already defaults to "real" on its own failures, so
    nothing here can raise."""
    if not targets:
        return {}
    work = {target: (lambda t=target: _crs_key_basis(client, *t)) for target in targets}
    return _run_bounded(work)


def _aggregate_basis(bases: set[str]) -> str:
    """Roll a per-model set of contributing key bases into one label: `notional`
    only when every contributing key is subscription-backed, else `real` (a
    single pay-per-token key makes the sum a real spend figure)."""
    return "notional" if bases == {"notional"} else "real"


def sync_crs(
    user_id: int,
    synced_at: str | None = None,
    *,
    client: httpx.Client | None = None,
    key_basis: dict[tuple[str, str], str] | None = None,
    targets: list[tuple[str, str]] | None = None,
    fetched: dict[tuple[str, str], list[dict]] | None = None,
) -> dict:
    """Pull today's per-model usage across all distinct CRS keys, SUM per model, and
    upsert as global source='crs' scope='aggregate' rows (one row per model).

    `client` / `key_basis` / `targets` let `sync()` share one connection-pooled
    client, one already-resolved basis map, and one target enumeration across
    the daily + hourly grains of a single sync() call; a standalone caller
    (tests, CLI) that omits them gets an owned client and resolves its own
    basis exactly as before. `fetched` additionally lets `sync()` submit this
    grain's per-key reads into one merged bounded batch alongside basis and
    hourly reads instead of a separate wave; a standalone caller that omits it
    still fetches (with the same bounded concurrency) on its own.
    """
    targets = targets if targets is not None else _crs_targets(user_id)
    if not targets:
        return {"source": "crs", "status": "skip", "reason": "no cr_ keys in bot_configs", "rows": 0}

    owns_client = client is None
    client = client or new_http_client()
    try:
        basis_map = key_basis if key_basis is not None else resolve_key_basis(client, targets)

        # Independent per-key reads run with bounded concurrency; failures are
        # collected and checked in original target order below so a failing
        # key aborts the sync deterministically, same as the prior sequential
        # fail-fast loop (no partial-grain upsert on any key's failure).
        if fetched is None:
            fetch_work = {target: (lambda t=target: _fetch_crs_key(client, *t)) for target in targets}
            fetched = _run_bounded(fetch_work)
        for target in targets:
            result = fetched[target]
            if isinstance(result, Exception):
                logger.opt(exception=result).error("sync_crs: fetch failed for a key: {}", result)
                return {"source": "crs", "status": "error", "reason": str(result), "rows": 0}

        # model -> summed totals across every distinct key (the global per-model aggregate).
        agg: dict[str, dict] = {}
        agg_basis: dict[str, set] = {}
        for target in targets:
            basis = basis_map.get(target, "real")
            for item in fetched[target]:
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
    finally:
        if owns_client:
            client.close()

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
    """Run the enabled source pulls. `source` filters to one of crs.

    When CRS is enabled, also pulls hourly for [yesterday, today] into
    model_usage_hourly (todo 3165). Daily-only filtering is still available
    via the same `source` switch — there is no separate hourly source value.

    Completes synchronously after both grains persist (no background
    enqueue). Basis lookups, the daily grain's per-key fetch, and the hourly
    grain's per-(date, key) fetch are all independent of each other (basis is
    only consumed at aggregation time), so they are submitted into one merged
    bounded batch here instead of three sequential bounded waves (todo 3520
    review round 1): resolving basis, then fetching daily, then fetching
    hourly one after another cost roughly a full extra wave of upstream
    latency for no semantic benefit. Each grain still checks and aggregates
    only its own fetch results afterwards, so a failing daily key cannot
    block the hourly upsert (or vice versa) — same per-grain independence as
    before, just resolved from one shared batch instead of three.
    """
    synced_at = get_utc_iso8601_timestamp()
    results = []
    if source in (None, "crs"):
        # Import lazily to avoid a circular import at module load (hourly
        # imports daily helpers for key/basis).
        from storage.service import model_usage_hourly as hourly_service

        targets = _crs_targets(user_id)
        date_list = hourly_service.default_hourly_dates()
        with new_http_client() as client:
            basis_work = {("basis", *t): (lambda t=t: _crs_key_basis(client, *t)) for t in targets}
            daily_work = {("daily", *t): (lambda t=t: _fetch_crs_key(client, *t)) for t in targets}
            hourly_work = {
                ("hourly", d, *t): (lambda t=t, d=d: hourly_service._fetch_crs_key_hourly(client, t[0], t[1], d))
                for d in date_list for t in targets
            }
            settled = _run_bounded({**basis_work, **daily_work, **hourly_work})

            key_basis = {t: settled[("basis", *t)] for t in targets}
            daily_fetched = {t: settled[("daily", *t)] for t in targets}
            hourly_fetched = {(d, *t): settled[("hourly", d, *t)] for d in date_list for t in targets}

            results.append(sync_crs(
                user_id, synced_at, client=client, key_basis=key_basis, targets=targets, fetched=daily_fetched,
            ))
            results.append(hourly_service.sync_crs_hourly(
                user_id, dates=date_list, synced_at=synced_at, client=client,
                key_basis=key_basis, targets=targets, fetched=hourly_fetched,
            ))
    return {"status": "ok", "results": results}
