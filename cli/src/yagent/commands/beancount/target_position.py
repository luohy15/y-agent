"""Fetch market position data from various APIs and output as JSON."""

import click
import httpx

from .alphavantage import get_api_key, query

VIX_CSV_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"


def _fetch_spy_weekly(client: httpx.Client, api_key: str) -> tuple[dict, float | None]:
    """Fetch SPY weekly adjusted data. Returns (latest_entry, 52-week high)."""
    data = query(client, api_key, {"function": "TIME_SERIES_WEEKLY_ADJUSTED", "symbol": "SPY"})
    ts = data.get("Weekly Adjusted Time Series", {})
    if not ts:
        return {}, None
    dates = sorted(ts.keys(), reverse=True)
    latest = {"date": dates[0], **ts[dates[0]]}
    # ~52 weeks for 52-week high
    year_dates = dates[:52]
    recent_high = max(float(ts[d]["2. high"]) for d in year_dates)
    return latest, recent_high


def _fetch_spy_rsi(client: httpx.Client, api_key: str) -> float | None:
    """Fetch SPY RSI(14) daily."""
    data = query(client, api_key, {
        "function": "RSI", "symbol": "SPY",
        "interval": "daily", "time_period": "14", "series_type": "close",
    })
    ts = data.get("Technical Analysis: RSI", {})
    if not ts:
        return None
    latest_date = max(ts.keys())
    return float(ts[latest_date]["RSI"])


def _fetch_vix(client: httpx.Client) -> float | None:
    """Fetch latest VIX close from CBOE historical CSV."""
    resp = client.get(VIX_CSV_URL, timeout=30)
    resp.raise_for_status()
    # Last non-empty line has the latest data: DATE,OPEN,HIGH,LOW,CLOSE
    for line in reversed(resp.text.strip().splitlines()):
        row = line.split(",")
        if len(row) >= 5:
            try:
                return float(row[4])
            except ValueError:
                continue
    return None


def _fetch_treasury_yield(client: httpx.Client, api_key: str, maturity: str) -> str:
    """Fetch treasury yield (2year or 10year)."""
    data = query(client, api_key, {"function": "TREASURY_YIELD", "interval": "daily", "maturity": maturity})
    data_points = data.get("data", [])
    return data_points[0].get("value", "") if data_points else ""


def _fetch_news_sentiment(client: httpx.Client, api_key: str) -> float | None:
    """Fetch average SPY news sentiment score."""
    data = query(client, api_key, {"function": "NEWS_SENTIMENT", "tickers": "SPY", "limit": "20"})
    feed = data.get("feed", [])
    if not feed:
        return None
    scores = []
    for article in feed:
        for ts in article.get("ticker_sentiment", []):
            if ts.get("ticker") == "SPY":
                try:
                    scores.append(float(ts["ticker_sentiment_score"]))
                except (ValueError, TypeError, KeyError):
                    pass
    return sum(scores) / len(scores) if scores else None


def _calc_target_ratio(rsi: float | None, drawdown_pct: float | None,
                       vix: float | None, yield_spread_bps: float | None,
                       sentiment: float | None) -> float:
    """Calculate target stock position ratio from market signals.

    Two-layer approach to prevent double-counting:
    - Primary signal: max of drawdown and VIX (both measure fear, take the stronger one)
    - Secondary signals: RSI, yield curve, sentiment (independent, additive)
    Base: 0.80 (neutral), clamped to [0.60, 1.00].
    """
    target = 0.80

    # --- Primary: fear signal (take max of drawdown and VIX to avoid double-count) ---
    fear_adj = 0.0
    if drawdown_pct is not None:
        if drawdown_pct > 20:
            fear_adj = max(fear_adj, 0.20)
        elif drawdown_pct > 10:
            fear_adj = max(fear_adj, 0.10)
        elif drawdown_pct > 5:
            fear_adj = max(fear_adj, 0.05)
    if vix is not None:
        if vix > 35:
            fear_adj = max(fear_adj, 0.15)
        elif vix > 25:
            fear_adj = max(fear_adj, 0.05)
    target += fear_adj

    # --- Primary: greed signal (low VIX = complacency) ---
    if vix is not None and vix < 15 and (drawdown_pct is None or drawdown_pct < 2):
        target -= 0.05

    # --- Secondary: RSI momentum ---
    if rsi is not None:
        if rsi > 70:
            target -= 0.05
        elif rsi < 30:
            target += 0.05

    # --- Secondary: yield curve inversion ---
    if yield_spread_bps is not None and yield_spread_bps < 0:
        target -= 0.05

    # --- Secondary: sentiment ---
    if sentiment is not None:
        if sentiment < -0.15:
            target -= 0.05
        elif sentiment > 0.15:
            target += 0.05

    return round(max(0.60, min(1.00, target)), 2)


@click.command("target-position")
def target_position():
    """Fetch market position data (SPY, yields, sentiment) and compute target ratio."""
    api_key = get_api_key()

    with httpx.Client() as client:
        spy_weekly, high_52w = _fetch_spy_weekly(client, api_key)
        rsi = _fetch_spy_rsi(client, api_key)
        vix = _fetch_vix(client)
        yield_2y = _fetch_treasury_yield(client, api_key, "2year")
        yield_10y = _fetch_treasury_yield(client, api_key, "10year")
        avg_sentiment = _fetch_news_sentiment(client, api_key)

    spy_price = spy_weekly.get("4. close", "")

    # drawdown from 52-week high (%)
    try:
        drawdown_pct = round((1 - float(spy_price) / high_52w) * 100, 2) if spy_price and high_52w else None
    except (ValueError, TypeError):
        drawdown_pct = None

    # yield spread in basis points
    try:
        spread = round((float(yield_10y) - float(yield_2y)) * 100, 2) if yield_2y and yield_10y else None
    except (ValueError, TypeError):
        spread = None

    target_ratio = _calc_target_ratio(rsi, drawdown_pct, vix, spread, avg_sentiment)

    result = {
        "spy_price": spy_price,
        "spy_high_52w": high_52w,
        "spy_drawdown_pct": drawdown_pct,
        "spy_rsi": round(rsi, 2) if rsi is not None else None,
        "vix": vix,
        "yield_2y": yield_2y,
        "yield_10y": yield_10y,
        "yield_spread_bps": spread,
        "avg_sentiment": round(avg_sentiment, 4) if avg_sentiment is not None else None,
        "target_ratio": target_ratio,
    }
    from .helpers import save_and_echo
    save_and_echo("target_position", result)
