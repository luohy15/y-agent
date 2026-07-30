"""Alpha Vantage live price-series pass-through for the ticker chart (todo 2932).

Pure pass-through by explicit constraint: no DB table, no in-process memo, no TTL
wrapper, and no stale fallback. Every call issues one upstream request and the
result is trimmed to the requested range server-side, then handed straight to the
caller. The server owns the range -> interval table (plan D2); the client only
ever names a range token.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from loguru import logger

from storage.service.finance_av import av_aware_utc
from storage.service.finance_realtime_quote import AV_BASE, _is_av_error
from storage.service.finance_realtime_quote import api_key as realtime_api_key

# Regular-hours vs extended-hours intraday bars. Roy has not confirmed this yet
# (plan D6 / open decision 1) - keep it a single named constant so flipping the
# default is a one-line change, not a threaded parameter.
EXTENDED_HOURS_DEFAULT = False

_TIMEOUT_SECONDS = 15.0


class PriceSeriesError(Exception):
    """Raised for provider/config failures; `kind` maps to an HTTP status (plan D10)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind  # "not_configured" | "not_found" | "throttled" | "upstream"


@dataclass(frozen=True)
class PriceBar:
    time: datetime  # aware UTC instant
    open: float
    high: float
    low: float
    close: float
    volume: int | None

    def to_dict(self) -> dict:
        return {
            "time": _format_iso(self.time),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass(frozen=True)
class PriceSeriesResult:
    symbol: str
    range: str
    interval: str
    bars: list[PriceBar]
    from_date: date | None  # None for "all": there is no floor, only the first bar returned
    to_date: date
    currency: str
    fetched_at: datetime

    def to_envelope(self) -> dict:
        return {
            "data": [bar.to_dict() for bar in self.bars],
            "symbol": self.symbol,
            "range": self.range,
            "interval": self.interval,
            "from": self.from_date.isoformat() if self.from_date else None,
            "to": self.to_date.isoformat(),
            "currency": self.currency,
            "fetched_at": _format_iso(self.fetched_at),
            "source": "alphavantage",
        }


@dataclass(frozen=True)
class _RangeSpec:
    interval: str
    kind: str  # "intraday" | "daily" | "weekly"
    av_interval: str | None  # AV's `interval` param for intraday, e.g. "15min"
    span_days: int | None  # trailing calendar days; None means "year to date" / unbounded


# Server-owned range -> interval table (plan D2). Implemented in full even though the
# UI may ship fewer range buttons.
RANGE_TABLE: dict[str, _RangeSpec] = {
    "1w": _RangeSpec(interval="15min", kind="intraday", av_interval="15min", span_days=7),
    "1m": _RangeSpec(interval="30min", kind="intraday", av_interval="30min", span_days=30),
    "3m": _RangeSpec(interval="daily", kind="daily", av_interval=None, span_days=90),
    "ytd": _RangeSpec(interval="daily", kind="daily", av_interval=None, span_days=None),
    "1y": _RangeSpec(interval="daily", kind="daily", av_interval=None, span_days=365),
    "5y": _RangeSpec(interval="weekly", kind="weekly", av_interval=None, span_days=1825),
    "all": _RangeSpec(interval="weekly", kind="weekly", av_interval=None, span_days=None),
}

_AV_FUNCTION = {"intraday": "TIME_SERIES_INTRADAY", "daily": "TIME_SERIES_DAILY_ADJUSTED", "weekly": "TIME_SERIES_WEEKLY_ADJUSTED"}
_AV_TIME_SERIES_KEY = {"daily": "Time Series (Daily)", "weekly": "Weekly Adjusted Time Series"}


def api_key() -> str | None:
    return realtime_api_key()


def fetch(symbol: str, range_token: str, *, today: date | None = None) -> PriceSeriesResult:
    normalized_symbol = (symbol or "").strip().upper()
    if not normalized_symbol:
        raise PriceSeriesError("not_found", "symbol is required")

    normalized_range = (range_token or "").strip().lower()
    spec = RANGE_TABLE.get(normalized_range)
    if spec is None:
        raise PriceSeriesError("not_found", f"unsupported range: {range_token!r}")

    key = api_key()
    if not key:
        raise PriceSeriesError("not_configured", "ALPHAVANTAGE_API_KEY is not configured")

    now = datetime.now(UTC)
    resolved_today = today or now.date()
    from_date, to_date = _span_for(spec, resolved_today)

    logger.info("fetching AV price series for {} range={} interval={}", normalized_symbol, normalized_range, spec.interval)
    try:
        payload = _fetch_uncached(normalized_symbol, spec, key)
    except (httpx.HTTPError, ValueError) as exc:
        # ValueError also covers response.json() raising on a non-JSON upstream body.
        raise PriceSeriesError("upstream", str(exc)) from exc

    if _is_av_error(payload):
        kind, detail = _classify_av_error(payload)
        raise PriceSeriesError(kind, detail)

    bars = _parse_bars(payload, spec, from_date=from_date, to_date=to_date)
    bars.sort(key=lambda bar: bar.time)
    # "all" has no floor; report the actual first bar's date rather than a sentinel.
    effective_from_date = from_date if from_date is not None else (bars[0].time.date() if bars else None)

    return PriceSeriesResult(
        symbol=normalized_symbol,
        range=normalized_range,
        interval=spec.interval,
        bars=bars,
        from_date=effective_from_date,
        to_date=to_date,
        currency="USD",
        fetched_at=now,
    )


def _span_for(spec: _RangeSpec, today: date) -> tuple[date | None, date]:
    if spec.span_days is None:
        # "ytd" spans this calendar year to date; "all" is unbounded (no floor).
        from_date = date(today.year, 1, 1) if spec.kind == "daily" else None
        return from_date, today
    return today - timedelta(days=spec.span_days - 1), today


def _fetch_uncached(symbol: str, spec: _RangeSpec, key: str) -> dict:
    params: dict[str, str] = {"symbol": symbol, "apikey": key, "datatype": "json"}
    if spec.kind == "intraday":
        params.update({
            "function": _AV_FUNCTION["intraday"],
            "interval": spec.av_interval,
            "outputsize": "full",
            "extended_hours": "true" if EXTENDED_HOURS_DEFAULT else "false",
        })
    else:
        params["function"] = _AV_FUNCTION[spec.kind]
        if spec.kind == "daily":
            params["outputsize"] = "full"
    response = httpx.get(AV_BASE, params=params, timeout=_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def _classify_av_error(payload: dict) -> tuple[str, str]:
    if "Error Message" in payload:
        return "not_found", str(payload["Error Message"])
    if "Note" in payload:
        return "throttled", str(payload["Note"])
    if "Information" in payload:
        return "throttled", str(payload["Information"])
    return "upstream", str(payload)


def _parse_bars(payload: Any, spec: _RangeSpec, *, from_date: date | None, to_date: date) -> list[PriceBar]:
    if spec.kind == "intraday":
        series_key = f"Time Series ({spec.av_interval})"
    else:
        series_key = _AV_TIME_SERIES_KEY[spec.kind]
    rows = payload.get(series_key) if isinstance(payload, dict) else None
    if not isinstance(rows, dict):
        logger.warning("AV {} response missing {!r}", _AV_FUNCTION[spec.kind], series_key)
        return []

    bars: list[PriceBar] = []
    for key_str, row in rows.items():
        if not isinstance(row, dict):
            continue
        if spec.kind == "intraday":
            bar = _parse_intraday_bar(key_str, row)
        else:
            bar = _parse_daily_or_weekly_bar(key_str, row)
        if bar is None:
            continue
        if (from_date is None or from_date <= bar.time.date()) and bar.time.date() <= to_date:
            bars.append(bar)
    return bars


def _parse_intraday_bar(key_str: str, row: dict) -> PriceBar | None:
    try:
        naive = datetime.strptime(key_str, "%Y-%m-%d %H:%M:%S")
        return PriceBar(
            time=av_aware_utc(naive),
            open=float(row["1. open"]),
            high=float(row["2. high"]),
            low=float(row["3. low"]),
            close=float(row["4. close"]),
            volume=int(float(row["5. volume"])),
        )
    except (KeyError, ValueError) as exc:
        logger.warning("skipping malformed AV intraday bar {}: {}", key_str, exc)
        return None


def _parse_daily_or_weekly_bar(key_str: str, row: dict) -> PriceBar | None:
    try:
        day = date.fromisoformat(key_str)
        close = float(row["4. close"])
        adjusted_close = float(row["5. adjusted close"])
        # Scale open/high/low by the same split/dividend adjustment factor as close,
        # so a bar stays internally consistent (plan D4).
        factor = adjusted_close / close if close else 1.0
        return PriceBar(
            time=datetime(day.year, day.month, day.day, tzinfo=UTC),
            open=float(row["1. open"]) * factor,
            high=float(row["2. high"]) * factor,
            low=float(row["3. low"]) * factor,
            close=adjusted_close,
            volume=int(float(row["6. volume"])),
        )
    except (KeyError, ValueError) as exc:
        logger.warning("skipping malformed AV daily/weekly bar {}: {}", key_str, exc)
        return None


def _format_iso(value: datetime) -> str:
    aware = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.isoformat().replace("+00:00", "Z")
