"""Alpha Vantage company fundamentals cache for the ticker analysis page."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from loguru import logger

from storage.repository import finance_fundamentals as repo
from storage.service.finance_realtime_quote import api_key as realtime_api_key

AV_BASE = "https://www.alphavantage.co/query"

# Five AV functions fetched as one batch per symbol.
_AV_FUNCTIONS = (
    ("OVERVIEW", "overview"),
    ("BALANCE_SHEET", "balance_sheet"),
    ("INCOME_STATEMENT", "income_statement"),
    ("CASH_FLOW", "cash_flow"),
    ("EARNINGS", "earnings"),
)


@dataclass(frozen=True)
class FundamentalsResult:
    symbol: str
    overview: dict | None
    balance_sheet: dict | None
    income_statement: dict | None
    cash_flow: dict | None
    earnings: dict | None
    metrics: dict
    fetched_at: datetime | None
    source: str  # live | cache | partial

    def to_envelope(self, include_raw: bool = False) -> dict:
        """Envelope for the API / CLI.

        The raw AV statement bodies are ~380KB per symbol and nothing but `metrics`
        (plus a couple of `overview` fields) is rendered, so they are opt-in.
        """
        data = {
            "symbol": self.symbol,
            "overview": self.overview,
            "metrics": self.metrics,
        }
        if include_raw:
            data["balance_sheet"] = self.balance_sheet
            data["income_statement"] = self.income_statement
            data["cash_flow"] = self.cash_flow
            data["earnings"] = self.earnings
        return {
            "data": data,
            "fetched_at": _format_iso(self.fetched_at) if self.fetched_at else "",
            "source": self.source,
        }


def api_key() -> str | None:
    return realtime_api_key()


def fetch(symbol: str, ttl_seconds: float | None = None) -> FundamentalsResult:
    normalized = (symbol or "").strip().upper()
    if not normalized:
        return FundamentalsResult(
            symbol="",
            overview=None,
            balance_sheet=None,
            income_statement=None,
            cash_flow=None,
            earnings=None,
            metrics=_empty_metrics(),
            fetched_at=None,
            source="cache",
        )

    existing = repo.get(normalized)
    now = datetime.now(UTC)
    ttl = _ttl_seconds() if ttl_seconds is None else max(0.0, float(ttl_seconds))
    cutoff = now - timedelta(seconds=ttl)
    fresh = existing is not None and _as_aware_utc(existing["fetched_at"]) >= cutoff
    if fresh:
        return _row_to_result(existing, source="cache")

    try:
        payloads = _fetch_all_uncached(normalized)
    except (RuntimeError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        if existing:
            age = now - _as_aware_utc(existing["fetched_at"])
            logger.warning(
                "failed to fetch AV fundamentals for {}; returning stale row {} old: {}",
                normalized,
                age,
                exc,
            )
            return _row_to_result(existing, source="partial")
        logger.warning("failed to fetch AV fundamentals for {}: {}", normalized, exc)
        return FundamentalsResult(
            symbol=normalized,
            overview=None,
            balance_sheet=None,
            income_statement=None,
            cash_flow=None,
            earnings=None,
            metrics=_empty_metrics(),
            fetched_at=None,
            source="partial",
        )

    fetched_at = datetime.now(UTC)
    row = repo.upsert(
        {
            "symbol": normalized,
            "overview": payloads.get("overview"),
            "balance_sheet": payloads.get("balance_sheet"),
            "income_statement": payloads.get("income_statement"),
            "cash_flow": payloads.get("cash_flow"),
            "earnings": payloads.get("earnings"),
            "fetched_at": fetched_at,
        }
    )
    return _row_to_result(row, source="live")


def compute_metrics(
    overview: dict | None,
    balance_sheet: dict | None,
    income_statement: dict | None,
    cash_flow: dict | None,
    earnings: dict | None = None,
) -> dict:
    """Compute the metrics block from cached AV statement bodies.

    Formulas follow pages/finance-metrics.md. Missing inputs yield null values.
    AV "None" string sentinels are treated as null.
    """
    ov = overview if isinstance(overview, dict) else {}
    bs_reports = _annual_reports(balance_sheet)
    is_reports = _annual_reports(income_statement)
    cf_reports = _annual_reports(cash_flow)
    bs0 = bs_reports[0] if bs_reports else {}
    bs1 = bs_reports[1] if len(bs_reports) > 1 else {}
    is0 = is_reports[0] if is_reports else {}
    is1 = is_reports[1] if len(is_reports) > 1 else {}
    cf0 = cf_reports[0] if cf_reports else {}

    # --- Market / Valuation (prefer OVERVIEW; fall back to derived) ---
    market_cap = _num(ov.get("MarketCapitalization"))
    pe = _num(ov.get("PERatio"))
    ps = _num(ov.get("PriceToSalesRatioTTM"))
    pb = _num(ov.get("PriceToBookRatio"))
    # AV returns ROE / DividendYield as decimals (0.55 = 55%).
    roe_overview = _pct_from_decimal(_num(ov.get("ReturnOnEquityTTM")))
    div_yield = _pct_from_decimal(_num(ov.get("DividendYield")))
    peg_overview = _num(ov.get("PEGRatio"))

    # --- Balance sheet ---
    assets = _num(bs0.get("totalAssets"))
    liabilities = _num(bs0.get("totalLiabilities"))
    equity = _num(bs0.get("totalShareholderEquity"))
    if equity is None and assets is not None and liabilities is not None:
        equity = assets - liabilities
    leverage = _div(assets, equity)

    # --- Income statement ---
    revenue = _num(is0.get("totalRevenue"))
    cogs = _num(is0.get("costOfRevenue"))
    net_income = _num(is0.get("netIncome"))
    # Doc identity: Net Income = Revenue - Expenses, so total expenses are the residual.
    # AV's operatingExpenses is only R&D + SG&A (no COGS, no tax) and would give every
    # company a "good control" expense ratio, so it is the fallback, not the preference.
    if revenue is not None and net_income is not None:
        expenses = revenue - net_income
    else:
        expenses = _num(is0.get("operatingExpenses"))
    expense_ratio = _pct(_div(expenses, revenue))

    # --- Profitability ---
    gross_margin = None
    if revenue and cogs is not None and revenue != 0:
        gross_margin = _pct((revenue - cogs) / revenue)
    elif revenue and _num(is0.get("grossProfit")) is not None:
        gross_margin = _pct(_div(_num(is0.get("grossProfit")), revenue))
    net_margin = _pct(_div(net_income, revenue))
    # AV has no dedicated sales / admin split, so the doc's Sales / Admin Expense Ratio
    # cannot be computed. Report the two line items AV does give under their real names
    # instead of relabelling them as something they are not.
    sga = _num(is0.get("sellingGeneralAndAdministrative"))
    sga_expense_ratio = _pct(_div(sga, revenue))
    rd = _num(is0.get("researchAndDevelopment"))
    rd_expense_ratio = _pct(_div(rd, revenue))
    interest_exp = _num(is0.get("interestExpense"))
    finance_expense_ratio = _pct(_div(interest_exp, revenue))
    roa = _pct(_div(net_income, assets))
    roe = roe_overview if roe_overview is not None else _pct(_div(net_income, equity))

    # --- Growth (YoY annual) ---
    rev1 = _num(is1.get("totalRevenue"))
    ni1 = _num(is1.get("netIncome"))
    eq1 = _num(bs1.get("totalShareholderEquity"))
    as1 = _num(bs1.get("totalAssets"))
    revenue_growth = _pct(_growth(revenue, rev1))
    profit_growth = _pct(_growth(net_income, ni1))
    equity_growth = _pct(_growth(equity, eq1))
    asset_growth = _pct(_growth(assets, as1))
    # PEG = PE / Profit Growth Rate (growth as percentage points, e.g. 25 not 0.25)
    peg = None
    if pe is not None and profit_growth is not None and profit_growth != 0:
        peg = pe / profit_growth
    elif peg_overview is not None:
        peg = peg_overview

    # --- Cash flow ---
    ocf = _num(cf0.get("operatingCashflow"))
    capex = _num(cf0.get("capitalExpenditures"))
    # CapEx is typically reported as negative outflow; FCF = OCF - CapEx with CapEx as abs
    # outflow. Missing CapEx yields null rather than OCF, which would understate spending.
    fcf = None
    if ocf is not None and capex is not None:
        fcf = ocf - abs(capex)

    # --- Solvency ---
    short_debt = _num(bs0.get("shortTermDebt"))
    long_debt = _num(bs0.get("longTermDebt"))
    # Prefer explicit total debt fields when present. Explicit None checks throughout so a
    # debt-free company reports 0%, not "missing".
    total_debt = _num(bs0.get("shortLongTermDebtTotal"))
    if total_debt is None:
        total_debt = _num(bs0.get("longTermDebtNoncurrent"))
    if total_debt is None and (short_debt is not None or long_debt is not None):
        total_debt = (short_debt or 0.0) + (long_debt or 0.0)
    debt_to_asset = _pct(_div(total_debt, assets))
    years_to_clear = _div(total_debt, net_income) if net_income and net_income > 0 else None
    current_assets = _num(bs0.get("totalCurrentAssets"))
    current_liab = _num(bs0.get("totalCurrentLiabilities"))
    inventory = _num(bs0.get("inventory")) or 0.0
    current_ratio = _div(current_assets, current_liab)
    quick_ratio = None
    if current_assets is not None and current_liab:
        quick_ratio = (current_assets - inventory) / current_liab

    return {
        "market": {
            "market_cap": market_cap,
            "dividend_yield": div_yield,
        },
        "valuation": {
            "pe_ratio": pe,
            "ps_ratio": ps,
            "pb_ratio": pb,
            "roe": roe,
        },
        "balance_sheet": {
            "assets": assets,
            "liabilities": liabilities,
            "equity": equity,
            "leverage_ratio": leverage,
            "fiscal_date": bs0.get("fiscalDateEnding"),
        },
        "income_statement": {
            "revenue": revenue,
            "expenses": expenses,
            "net_income": net_income,
            "expense_ratio": expense_ratio,
            "fiscal_date": is0.get("fiscalDateEnding"),
        },
        "profitability": {
            "gross_margin": gross_margin,
            "net_margin": net_margin,
            "sga_expense_ratio": sga_expense_ratio,
            "rd_expense_ratio": rd_expense_ratio,
            "finance_expense_ratio": finance_expense_ratio,
            "roa": roa,
            "roe": roe,
        },
        "growth": {
            "revenue_growth": revenue_growth,
            "profit_growth": profit_growth,
            "equity_growth": equity_growth,
            "asset_growth": asset_growth,
            "peg": peg,
        },
        "cash_flow": {
            "operating_cash_flow": ocf,
            "free_cash_flow": fcf,
            "fiscal_date": cf0.get("fiscalDateEnding"),
        },
        "solvency": {
            "debt_to_asset": debt_to_asset,
            "years_to_clear_debt": years_to_clear,
            "current_ratio": current_ratio,
            "quick_ratio": quick_ratio,
        },
        "earnings_history": _earnings_history(earnings),
    }


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _row_to_result(row: dict, source: str) -> FundamentalsResult:
    overview = row.get("overview")
    balance_sheet = row.get("balance_sheet")
    income_statement = row.get("income_statement")
    cash_flow = row.get("cash_flow")
    earnings = row.get("earnings")
    metrics = compute_metrics(overview, balance_sheet, income_statement, cash_flow, earnings)
    return FundamentalsResult(
        symbol=row["symbol"],
        overview=overview if isinstance(overview, dict) else None,
        balance_sheet=balance_sheet if isinstance(balance_sheet, dict) else None,
        income_statement=income_statement if isinstance(income_statement, dict) else None,
        cash_flow=cash_flow if isinstance(cash_flow, dict) else None,
        earnings=earnings if isinstance(earnings, dict) else None,
        metrics=metrics,
        fetched_at=_as_aware_utc(row["fetched_at"]) if row.get("fetched_at") else None,
        source=source,
    )


def _fetch_all_uncached(symbol: str) -> dict[str, Any]:
    key = api_key()
    if not key:
        raise RuntimeError("ALPHAVANTAGE_API_KEY is not configured")
    out: dict[str, Any] = {}
    with httpx.Client(timeout=30) as client:
        for function, field in _AV_FUNCTIONS:
            logger.info("fetching AV {} for {}", function, symbol)
            response = client.get(
                AV_BASE,
                params={"function": function, "symbol": symbol, "apikey": key},
            )
            response.raise_for_status()
            data = response.json()
            if _is_av_error(data):
                raise RuntimeError(f"AV API error on {function}: {data}")
            if not isinstance(data, dict) or not data:
                logger.warning("AV {} for {} returned empty payload", function, symbol)
                out[field] = None
            else:
                out[field] = data
    return out


def _ttl_seconds() -> float:
    raw = os.environ.get("Y_AGENT_FUNDAMENTALS_TTL", "86400")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 86400.0


def _is_av_error(data: Any) -> bool:
    return isinstance(data, dict) and any(key in data for key in ("Error Message", "Information", "Note"))


def _annual_reports(payload: dict | None) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("annualReports")
    if not isinstance(rows, list):
        return []
    # AV returns newest-first; keep that order.
    return [r for r in rows if isinstance(r, dict)]


def _earnings_history(payload: dict | None) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("quarterlyEarnings")
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append(
            {
                "fiscal_date": r.get("fiscalDateEnding"),
                "reported_eps": _num(r.get("reportedEPS")),
                "estimated_eps": _num(r.get("estimatedEPS")),
                "surprise": _num(r.get("surprise")),
                "surprise_pct": _num(r.get("surprisePercentage")),
            }
        )
    return out


def _num(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in ("none", "null", "nan", "-", "n/a"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _pct(ratio: float | None) -> float | None:
    """Convert a 0-1 ratio to percentage points (0.15 → 15.0)."""
    if ratio is None:
        return None
    return ratio * 100.0


def _pct_from_decimal(value: float | None) -> float | None:
    """AV OVERVIEW returns ratios as decimals; convert to percentage points.

    Always scaled: AV never pre-scales these fields, so a value above 1 is a
    genuine >100% ratio (AAPL's TTM ROE is 1.415) and must not be passed through.
    """
    if value is None:
        return None
    return value * 100.0


def _growth(current: float | None, prior: float | None) -> float | None:
    # Deliberate divergence from the doc's "/ Prior": dividing by abs(prior) keeps the sign
    # meaningful when the prior period was a loss (loss → profit reads as positive growth).
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior)


def _empty_metrics() -> dict:
    return compute_metrics(None, None, None, None, None)


def _as_aware_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _format_iso(value: datetime) -> str:
    return _as_aware_utc(value).isoformat().replace("+00:00", "Z")
