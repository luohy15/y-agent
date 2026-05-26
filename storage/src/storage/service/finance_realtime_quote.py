"""Alpha Vantage realtime quote cache for finance holdings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from loguru import logger

from storage.repository import finance_realtime_quote as repo


AV_BASE = "https://www.alphavantage.co/query"


@dataclass(frozen=True)
class RealtimeQuote:
    symbol: str
    as_of: datetime
    close: float
    fetched_at: datetime

    def to_dict(self) -> dict:
        return {
            "price": self.close,
            "as_of": _format_iso(self.as_of),
            "currency": "USD",
        }


@dataclass(frozen=True)
class RealtimeQuoteResult:
    quotes: dict[str, RealtimeQuote]
    fetched_at: datetime | None
    source: str


def fetch_bulk(symbols: list[str] | tuple[str, ...] | set[str], ttl_seconds: float | None = None) -> RealtimeQuoteResult:
    normalized = tuple(sorted({symbol.strip().upper() for symbol in symbols if symbol and symbol.strip()}))
    if not normalized:
        return RealtimeQuoteResult(quotes={}, fetched_at=None, source="cache")

    existing = repo.get_many(list(normalized))
    now = datetime.now(UTC)
    ttl = _ttl_seconds() if ttl_seconds is None else max(0.0, float(ttl_seconds))
    cutoff = now - timedelta(seconds=ttl)
    stale = tuple(symbol for symbol in normalized if symbol not in existing or _as_aware_utc(existing[symbol]["fetched_at"]) < cutoff)
    if not stale:
        return RealtimeQuoteResult(quotes=_rows_to_quotes(existing, normalized), fetched_at=_max_fetched_at(existing), source="cache")

    try:
        quotes = _fetch_realtime_bulk_quotes_uncached(normalized)
    except (RuntimeError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        if existing:
            oldest = max(now - _as_aware_utc(row["fetched_at"]) for row in existing.values())
            logger.warning("failed to fetch realtime AV quotes for {}; returning stale DB quotes up to {} old: {}", normalized, oldest, exc)
            return RealtimeQuoteResult(quotes=_rows_to_quotes(existing, normalized), fetched_at=_max_fetched_at(existing), source="partial")
        logger.warning("failed to fetch realtime AV quotes for {}: {}", normalized, exc)
        return RealtimeQuoteResult(quotes={}, fetched_at=None, source="partial")

    fetched_at = datetime.now(UTC)
    repo.upsert_many([
        {"symbol": symbol, "as_of": quote.as_of, "close": quote.close, "fetched_at": fetched_at}
        for symbol, quote in quotes.items()
    ])
    merged = {**_rows_to_quotes(existing, normalized), **{symbol: RealtimeQuote(symbol=symbol, as_of=quote.as_of, close=quote.close, fetched_at=fetched_at) for symbol, quote in quotes.items()}}
    source = "live" if set(quotes) >= set(normalized) else "partial"
    return RealtimeQuoteResult(quotes={symbol: quote for symbol in normalized if (quote := merged.get(symbol)) is not None}, fetched_at=fetched_at, source=source)


def _ttl_seconds() -> float:
    raw = os.environ.get("Y_AGENT_REALTIME_QUOTES_TTL", "60")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 60.0


def api_key() -> str | None:
    key = os.getenv("ALPHAVANTAGE_API_KEY")
    return key.strip() if key and key.strip() else None


def _fetch_realtime_bulk_quotes_uncached(symbols: tuple[str, ...]) -> dict[str, RealtimeQuote]:
    key = api_key()
    if not key:
        raise RuntimeError("ALPHAVANTAGE_API_KEY is not configured")
    logger.info("fetching realtime AV quotes for {}", symbols)
    response = httpx.get(
        AV_BASE,
        params={
            "function": "REALTIME_BULK_QUOTES",
            "symbol": ",".join(symbols),
            "datatype": "json",
            "apikey": key,
        },
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if _is_av_error(data):
        raise RuntimeError(f"AV API error: {data}")
    return _decode_realtime_bulk_quotes(data)


def _decode_realtime_bulk_quotes(data: Any) -> dict[str, RealtimeQuote]:
    rows = data.get("stock_quotes") if isinstance(data, dict) else None
    if rows is None and isinstance(data, dict):
        rows = data.get("data")
    if not isinstance(rows, list):
        logger.warning("AV REALTIME_BULK_QUOTES response missing stock_quotes")
        return {}

    quotes: dict[str, RealtimeQuote] = {}
    fetched_at = datetime.now(UTC)
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _first_text(row, "symbol", "ticker")
        price = _to_float(_first_value(row, "price", "close", "last", "last_price"))
        as_of = _to_datetime(_first_value(row, "timestamp", "as_of", "last_updated", "time"))
        if symbol is None or price is None or as_of is None:
            logger.warning("skipping malformed realtime quote row: {}", row)
            continue
        symbol = symbol.upper()
        quotes[symbol] = RealtimeQuote(symbol=symbol, as_of=as_of, close=price, fetched_at=fetched_at)
    return quotes


def _rows_to_quotes(rows: dict[str, dict], symbols: tuple[str, ...]) -> dict[str, RealtimeQuote]:
    return {
        symbol: RealtimeQuote(
            symbol=symbol,
            as_of=_as_aware_utc(row["as_of"]),
            close=row["close"],
            fetched_at=_as_aware_utc(row["fetched_at"]),
        )
        for symbol in symbols
        if (row := rows.get(symbol)) is not None
    }


def _max_fetched_at(rows: dict[str, dict]) -> datetime | None:
    fetched = [_as_aware_utc(row["fetched_at"]) for row in rows.values()]
    return max(fetched) if fetched else None


def _is_av_error(data: Any) -> bool:
    return isinstance(data, dict) and any(key in data for key in ("Error Message", "Information", "Note"))


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _first_text(row: dict[str, Any], *keys: str) -> str | None:
    value = _first_value(row, *keys)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _as_aware_utc(value)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    return _as_aware_utc(parsed)


def _as_aware_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _format_iso(value: datetime) -> str:
    return _as_aware_utc(value).isoformat().replace("+00:00", "Z")
