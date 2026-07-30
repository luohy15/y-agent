import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import useSWR from "swr";
import {
  AreaSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { API, jsonFetcher as fetcher } from "../api";
import { useThemeColors, type ThemeColors } from "../host/theme";
import {
  buildTickerUniverse,
  classifyTxnType,
  entryPrice,
  entryShares,
  entryTicker,
  type TransactionRow,
} from "../lib/financeTransactions";
import { formatAmount, PRICE_RANGES, type FinancePriceRow, type PriceRange } from "../lib/finance";

// --- Types -----------------------------------------------------------------

// Narrower than FinanceViewer's envelope (which requires synced_at + a fixed source
// union); the fundamentals endpoint returns fetched_at instead.
interface FinanceEnvelope<T> {
  data: T;
  synced_at?: string;
  fetched_at?: string;
  source?: string;
}

interface FundamentalsMetrics {
  market: { market_cap: number | null; dividend_yield: number | null };
  valuation: { pe_ratio: number | null; ps_ratio: number | null; pb_ratio: number | null; roe: number | null };
  balance_sheet: {
    assets: number | null;
    liabilities: number | null;
    equity: number | null;
    leverage_ratio: number | null;
    fiscal_date?: string | null;
  };
  income_statement: {
    revenue: number | null;
    expenses: number | null;
    net_income: number | null;
    expense_ratio: number | null;
    fiscal_date?: string | null;
  };
  profitability: {
    gross_margin: number | null;
    net_margin: number | null;
    sga_expense_ratio: number | null;
    rd_expense_ratio: number | null;
    finance_expense_ratio: number | null;
    roa: number | null;
    roe: number | null;
  };
  growth: {
    revenue_growth: number | null;
    profit_growth: number | null;
    equity_growth: number | null;
    asset_growth: number | null;
    peg: number | null;
  };
  cash_flow: {
    operating_cash_flow: number | null;
    free_cash_flow: number | null;
    fiscal_date?: string | null;
  };
  solvency: {
    debt_to_asset: number | null;
    years_to_clear_debt: number | null;
    current_ratio: number | null;
    quick_ratio: number | null;
  };
  earnings_history: Array<{
    fiscal_date: string | null;
    reported_eps: number | null;
    estimated_eps: number | null;
    surprise: number | null;
    surprise_pct: number | null;
  }>;
}

interface FundamentalsData {
  symbol: string;
  overview: Record<string, unknown> | null;
  metrics: FundamentalsMetrics;
  // Raw AV statement bodies, only present with ?include_raw=true (unused here).
  balance_sheet?: unknown;
  income_statement?: unknown;
  cash_flow?: unknown;
  earnings?: unknown;
}

type MetricTab = "overview" | "financial" | "earnings" | "analysis";

const TABS: Array<{ id: MetricTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "financial", label: "Financial" },
  { id: "earnings", label: "Earnings" },
  { id: "analysis", label: "Analysis" },
];

// --- Formatting / threshold helpers ---------------------------------------

function formatCompact(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1_000_000_000_000) return `${sign}${(abs / 1_000_000_000_000).toFixed(2)}T`;
  if (abs >= 1_000_000_000) return `${sign}${(abs / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${sign}${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${sign}${(abs / 1_000).toFixed(2)}K`;
  return `${sign}${abs.toFixed(2)}`;
}

function formatPct(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

function formatRatio(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}x`;
}

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

type Tone = "good" | "warn" | "bad" | "neutral";

function toneClass(tone: Tone): string {
  switch (tone) {
    case "good": return "text-sol-green";
    case "warn": return "text-sol-yellow";
    case "bad": return "text-sol-red";
    default: return "text-sol-base0";
  }
}

function badgeClass(tone: Tone): string {
  switch (tone) {
    case "good": return "bg-sol-green/20 text-sol-green";
    case "warn": return "bg-sol-yellow/20 text-sol-yellow";
    case "bad": return "bg-sol-red/20 text-sol-red";
    default: return "bg-sol-base02 text-sol-base01";
  }
}

// Threshold bands from pages/finance-metrics.md
function peTone(v: number | null): { tone: Tone; label?: string } {
  if (v == null) return { tone: "neutral" };
  if (v < 10) return { tone: "good", label: "Undervalued" };
  if (v > 20) return { tone: "bad", label: "Overvalued" };
  if (v > 15) return { tone: "warn", label: "Elevated" };
  return { tone: "neutral" };
}

function pbTone(v: number | null): { tone: Tone; label?: string } {
  if (v == null) return { tone: "neutral" };
  if (v < 1) return { tone: "good", label: "Below book" };
  if (v > 5) return { tone: "bad", label: "Rich" };
  if (v > 3) return { tone: "warn" };
  return { tone: "neutral" };
}

function roeTone(v: number | null): { tone: Tone; label?: string } {
  if (v == null) return { tone: "neutral" };
  if (v > 20) return { tone: "good", label: "Outstanding" };
  if (v > 15) return { tone: "good", label: "Excellent" };
  return { tone: "neutral" };
}

function leverageTone(v: number | null): { tone: Tone; label?: string } {
  if (v == null) return { tone: "neutral" };
  if (v < 2) return { tone: "good", label: "Conservative" };
  if (v > 5) return { tone: "bad", label: "High" };
  return { tone: "warn", label: "Moderate" };
}

function expenseRatioTone(v: number | null): { tone: Tone; label?: string } {
  if (v == null) return { tone: "neutral" };
  if (v < 50) return { tone: "good", label: "Good control" };
  if (v > 80) return { tone: "bad", label: "High burden" };
  return { tone: "neutral" };
}

function netMarginTone(v: number | null): { tone: Tone; label?: string } {
  if (v == null) return { tone: "neutral" };
  if (v > 20) return { tone: "good", label: "Excellent" };
  if (v > 10) return { tone: "good", label: "Good" };
  return { tone: "neutral" };
}

function roaTone(v: number | null): { tone: Tone; label?: string } {
  if (v == null) return { tone: "neutral" };
  if (v > 10) return { tone: "good", label: "Excellent" };
  if (v > 5) return { tone: "good", label: "Good" };
  return { tone: "neutral" };
}

function growthTone(v: number | null): { tone: Tone; label?: string } {
  if (v == null) return { tone: "neutral" };
  if (v > 20) return { tone: "good", label: "High growth" };
  if (v > 10) return { tone: "good", label: "Steady" };
  if (v < 0) return { tone: "bad" };
  return { tone: "neutral" };
}

function pegTone(v: number | null): { tone: Tone; label?: string } {
  if (v == null) return { tone: "neutral" };
  if (v < 1) return { tone: "good", label: "Undervalued" };
  if (v > 2) return { tone: "bad", label: "Overvalued" };
  return { tone: "neutral" };
}

function debtToAssetTone(v: number | null): { tone: Tone; label?: string } {
  if (v == null) return { tone: "neutral" };
  if (v < 50) return { tone: "good", label: "Safe" };
  if (v > 70) return { tone: "bad", label: "High risk" };
  return { tone: "warn" };
}

function yearsToClearTone(v: number | null): { tone: Tone; label?: string } {
  if (v == null) return { tone: "neutral" };
  if (v < 3) return { tone: "good", label: "Good" };
  if (v > 5) return { tone: "bad", label: "High burden" };
  return { tone: "warn", label: "Moderate" };
}

function currentRatioTone(v: number | null): { tone: Tone; label?: string } {
  if (v == null) return { tone: "neutral" };
  if (v > 2) return { tone: "good", label: "Good liquidity" };
  if (v < 1) return { tone: "bad", label: "Pressure" };
  return { tone: "neutral" };
}

function quickRatioTone(v: number | null): { tone: Tone; label?: string } {
  if (v == null) return { tone: "neutral" };
  if (v > 1) return { tone: "good", label: "Safe" };
  return { tone: "warn" };
}

function dividendYieldTone(v: number | null): { tone: Tone; label?: string } {
  if (v == null) return { tone: "neutral" };
  if (v > 3) return { tone: "good", label: "Income stock" };
  return { tone: "neutral" };
}

function marketCapTone(v: number | null): { tone: Tone; label?: string } {
  if (v == null) return { tone: "neutral" };
  if (v > 100_000_000_000) return { tone: "neutral", label: "Large cap" };
  if (v > 20_000_000_000) return { tone: "neutral", label: "Mid cap" };
  return { tone: "neutral", label: "Small cap" };
}

function dateToUtcTimestamp(date: string): UTCTimestamp | null {
  // YYYY-MM-DD → UTC midnight so lightweight-charts business-day / UTC modes align.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!m) return null;
  const ms = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Math.floor(ms / 1000) as UTCTimestamp;
}

// --- Metric cell -----------------------------------------------------------

function MetricCell({
  label,
  value,
  tone = "neutral",
  badge,
}: {
  label: string;
  value: ReactNode;
  tone?: Tone;
  badge?: string;
}) {
  return (
    <div className="rounded border border-sol-base02 bg-sol-base03 px-3 py-2 min-w-0">
      <div className="text-sol-base01 text-[10px] uppercase tracking-wide mb-0.5 flex items-center gap-1.5">
        <span>{label}</span>
        {badge ? <span className={`rounded px-1 py-0.5 text-[9px] ${badgeClass(tone)}`}>{badge}</span> : null}
      </div>
      <div className={`text-sm tabular-nums font-medium ${toneClass(tone)}`}>{value}</div>
    </div>
  );
}

function MetricGrid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">{children}</div>;
}

function SectionTitle({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <div className="mb-2 mt-4 first:mt-0">
      <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">{children}</div>
      {hint ? <div className="text-sol-base01 text-[10px]">{hint}</div> : null}
    </div>
  );
}

// --- Tabs ------------------------------------------------------------------

function TickerOverviewTab({ metrics }: { metrics: FundamentalsMetrics }) {
  const pe = peTone(metrics.valuation.pe_ratio);
  const pb = pbTone(metrics.valuation.pb_ratio);
  const roe = roeTone(metrics.valuation.roe);
  const dy = dividendYieldTone(metrics.market.dividend_yield);
  const mc = marketCapTone(metrics.market.market_cap);
  return (
    <div>
      <SectionTitle hint="Market + valuation (Alpha Vantage OVERVIEW)">Overview</SectionTitle>
      <MetricGrid>
        <MetricCell label="Market Cap" value={formatCompact(metrics.market.market_cap)} tone={mc.tone} badge={mc.label} />
        <MetricCell label="P/E" value={formatNumber(metrics.valuation.pe_ratio)} tone={pe.tone} badge={pe.label} />
        <MetricCell label="P/S" value={formatNumber(metrics.valuation.ps_ratio)} />
        <MetricCell label="P/B" value={formatNumber(metrics.valuation.pb_ratio)} tone={pb.tone} badge={pb.label} />
        <MetricCell label="ROE" value={formatPct(metrics.valuation.roe)} tone={roe.tone} badge={roe.label} />
        <MetricCell label="Dividend Yield" value={formatPct(metrics.market.dividend_yield)} tone={dy.tone} badge={dy.label} />
      </MetricGrid>
    </div>
  );
}

function TickerFinancialTab({ metrics }: { metrics: FundamentalsMetrics }) {
  const lev = leverageTone(metrics.balance_sheet.leverage_ratio);
  const fiscal = metrics.balance_sheet.fiscal_date;
  return (
    <div>
      <SectionTitle hint={fiscal ? `Balance sheet · fiscal ${fiscal}` : "Balance sheet"}>Financial</SectionTitle>
      <MetricGrid>
        <MetricCell label="Assets" value={formatCompact(metrics.balance_sheet.assets)} />
        <MetricCell label="Liabilities" value={formatCompact(metrics.balance_sheet.liabilities)} />
        <MetricCell label="Equity" value={formatCompact(metrics.balance_sheet.equity)} />
        <MetricCell label="Leverage Ratio" value={formatRatio(metrics.balance_sheet.leverage_ratio)} tone={lev.tone} badge={lev.label} />
      </MetricGrid>
    </div>
  );
}

function TickerEarningsTab({ metrics }: { metrics: FundamentalsMetrics }) {
  const er = expenseRatioTone(metrics.income_statement.expense_ratio);
  const fiscal = metrics.income_statement.fiscal_date;
  const history = metrics.earnings_history || [];
  return (
    <div>
      <SectionTitle hint={fiscal ? `Income statement · fiscal ${fiscal}` : "Income statement"}>Earnings</SectionTitle>
      <MetricGrid>
        <MetricCell label="Revenue" value={formatCompact(metrics.income_statement.revenue)} />
        <MetricCell label="Expenses" value={formatCompact(metrics.income_statement.expenses)} />
        <MetricCell label="Net Income" value={formatCompact(metrics.income_statement.net_income)} />
        <MetricCell label="Expense Ratio" value={formatPct(metrics.income_statement.expense_ratio)} tone={er.tone} badge={er.label} />
      </MetricGrid>

      <SectionTitle hint="Quarterly EPS actual / estimate / surprise">EPS history</SectionTitle>
      {history.length === 0 ? (
        <div className="text-sol-base01 text-sm italic px-1">No earnings history</div>
      ) : (
        <div className="rounded border border-sol-base02 overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-sol-base01 border-b border-sol-base02 bg-sol-base02/50">
                <th className="text-left font-normal py-1 px-3">Fiscal</th>
                <th className="text-right font-normal py-1 px-3">Reported</th>
                <th className="text-right font-normal py-1 px-3">Estimate</th>
                <th className="text-right font-normal py-1 px-3">Surprise</th>
                <th className="text-right font-normal py-1 px-3">Surprise %</th>
              </tr>
            </thead>
            <tbody>
              {history.slice(0, 16).map((row, i) => {
                const surpriseTone: Tone =
                  row.surprise == null ? "neutral" : row.surprise > 0 ? "good" : row.surprise < 0 ? "bad" : "neutral";
                return (
                  <tr key={`${row.fiscal_date}-${i}`} className="hover:bg-sol-base02/40 border-b border-sol-base02/40">
                    <td className="py-0.5 px-3 text-sol-base0 tabular-nums">{row.fiscal_date || "—"}</td>
                    <td className="py-0.5 px-3 text-right tabular-nums text-sol-base0">{formatNumber(row.reported_eps, 4)}</td>
                    <td className="py-0.5 px-3 text-right tabular-nums text-sol-base0">{formatNumber(row.estimated_eps, 4)}</td>
                    <td className={`py-0.5 px-3 text-right tabular-nums ${toneClass(surpriseTone)}`}>{formatNumber(row.surprise, 4)}</td>
                    <td className={`py-0.5 px-3 text-right tabular-nums ${toneClass(surpriseTone)}`}>{formatPct(row.surprise_pct)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TickerAnalysisTab({ metrics }: { metrics: FundamentalsMetrics }) {
  const gm = metrics.profitability.gross_margin;
  const nm = netMarginTone(metrics.profitability.net_margin);
  const roa = roaTone(metrics.profitability.roa);
  const roe = roeTone(metrics.profitability.roe);
  const rg = growthTone(metrics.growth.revenue_growth);
  const pg = growthTone(metrics.growth.profit_growth);
  const peg = pegTone(metrics.growth.peg);
  const dta = debtToAssetTone(metrics.solvency.debt_to_asset);
  const ytc = yearsToClearTone(metrics.solvency.years_to_clear_debt);
  const cr = currentRatioTone(metrics.solvency.current_ratio);
  const qr = quickRatioTone(metrics.solvency.quick_ratio);

  return (
    <div>
      {/* Alpha Vantage has no sales / admin expense split, so the doc's Sales / Admin
          Expense Ratio are shown as the line items AV actually reports. */}
      <SectionTitle hint="Latest annual statements · ROE is TTM">Profitability</SectionTitle>
      <MetricGrid>
        <MetricCell label="Gross Margin" value={formatPct(gm)} />
        <MetricCell label="Net Margin" value={formatPct(metrics.profitability.net_margin)} tone={nm.tone} badge={nm.label} />
        <MetricCell label="SG&A / Revenue" value={formatPct(metrics.profitability.sga_expense_ratio)} />
        <MetricCell label="R&D / Revenue" value={formatPct(metrics.profitability.rd_expense_ratio)} />
        <MetricCell label="Interest / Revenue" value={formatPct(metrics.profitability.finance_expense_ratio)} />
        <MetricCell label="ROA" value={formatPct(metrics.profitability.roa)} tone={roa.tone} badge={roa.label} />
        <MetricCell label="ROE" value={formatPct(metrics.profitability.roe)} tone={roe.tone} badge={roe.label} />
      </MetricGrid>

      <SectionTitle>Growth</SectionTitle>
      <MetricGrid>
        <MetricCell label="Revenue Growth" value={formatPct(metrics.growth.revenue_growth)} tone={rg.tone} badge={rg.label} />
        <MetricCell label="Profit Growth" value={formatPct(metrics.growth.profit_growth)} tone={pg.tone} badge={pg.label} />
        <MetricCell label="Equity Growth" value={formatPct(metrics.growth.equity_growth)} />
        <MetricCell label="Asset Growth" value={formatPct(metrics.growth.asset_growth)} />
        <MetricCell label="PEG" value={formatNumber(metrics.growth.peg)} tone={peg.tone} badge={peg.label} />
      </MetricGrid>

      <SectionTitle hint={metrics.cash_flow.fiscal_date ? `Fiscal ${metrics.cash_flow.fiscal_date}` : undefined}>Cash Flow</SectionTitle>
      <MetricGrid>
        <MetricCell label="Operating CF" value={formatCompact(metrics.cash_flow.operating_cash_flow)} />
        <MetricCell label="Free Cash Flow" value={formatCompact(metrics.cash_flow.free_cash_flow)} />
      </MetricGrid>

      <SectionTitle>Solvency</SectionTitle>
      <MetricGrid>
        <MetricCell label="Debt-to-Asset" value={formatPct(metrics.solvency.debt_to_asset)} tone={dta.tone} badge={dta.label} />
        <MetricCell label="Years to Clear Debt" value={formatNumber(metrics.solvency.years_to_clear_debt)} tone={ytc.tone} badge={ytc.label} />
        <MetricCell label="Current Ratio" value={formatRatio(metrics.solvency.current_ratio)} tone={cr.tone} badge={cr.label} />
        <MetricCell label="Quick Ratio" value={formatRatio(metrics.solvency.quick_ratio)} tone={qr.tone} badge={qr.label} />
      </MetricGrid>
    </div>
  );
}

// --- Chart -----------------------------------------------------------------

function TickerChart({
  symbol,
  vmName,
  colors,
}: {
  symbol: string;
  vmName?: string | null;
  colors: ThemeColors;
}) {
  const [range, setRange] = useState<PriceRange>("YTD");
  const time = PRICE_RANGES.find((item) => item.label === range)?.value ?? "YTD";
  const priceParams = new URLSearchParams({ symbol, limit: "1000", time });
  if (vmName) priceParams.set("vm_name", vmName);
  const prices = useSWR<FinanceEnvelope<FinancePriceRow[]>>(
    `${API}/api/finance/prices?${priceParams.toString()}`,
    fetcher,
    { revalidateOnFocus: false },
  );

  const txnParams = new URLSearchParams({ symbol, limit: "500" });
  if (vmName) txnParams.set("vm_name", vmName);
  const txns = useSWR<FinanceEnvelope<TransactionRow[]>>(
    `${API}/api/finance/transactions?${txnParams.toString()}`,
    fetcher,
    { revalidateOnFocus: false },
  );

  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  const markersApiRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  const pricePoints = useMemo(() => {
    const rows = prices.data?.data ?? [];
    return rows
      .map((row) => {
        const t = dateToUtcTimestamp(row.price_date);
        if (t == null) return null;
        return { time: t as Time, value: row.price, date: row.price_date };
      })
      .filter((x): x is { time: Time; value: number; date: string } => x != null)
      .sort((a, b) => (a.time as number) - (b.time as number));
  }, [prices.data?.data]);

  const markers = useMemo(() => {
    const rows = txns.data?.data ?? [];
    const universe = buildTickerUniverse(rows);
    const out: SeriesMarker<Time>[] = [];
    for (const row of rows) {
      const type = classifyTxnType(row);
      if (type !== "buy" && type !== "sell") continue;
      const ticker = entryTicker(row, universe) || row.symbol;
      if (ticker.toUpperCase() !== symbol.toUpperCase()) continue;
      const t = dateToUtcTimestamp(row.transaction_date);
      if (t == null) continue;
      const price = entryPrice(row.postings || []);
      const shares = entryShares(row.postings || []);
      const shareN = shares.reduce((s, x) => s + Math.abs(x.amount), 0);
      const priceText = price ? ` @ $${formatAmount(price.amount)}` : "";
      const shareText = shareN ? ` ${formatAmount(shareN)}` : "";
      if (type === "buy") {
        out.push({
          time: t,
          position: "belowBar",
          color: colors.green,
          shape: "arrowUp",
          text: `Buy${shareText}${priceText}`,
        });
      } else {
        out.push({
          time: t,
          position: "aboveBar",
          color: colors.red,
          shape: "arrowDown",
          text: `Sell${shareText}${priceText}`,
        });
      }
    }
    // lightweight-charts requires markers sorted by time ascending
    out.sort((a, b) => (a.time as number) - (b.time as number));
    return out;
  }, [txns.data?.data, symbol, colors.green, colors.red]);

  // Drop markers outside the selected range: pricePoints is already range-filtered by the
  // API, and a marker with no bar to attach to is invisible but still counted otherwise.
  const visibleMarkers = useMemo(() => {
    if (pricePoints.length === 0) return [];
    const first = pricePoints[0].time as number;
    const last = pricePoints[pricePoints.length - 1].time as number;
    return markers.filter((m) => (m.time as number) >= first && (m.time as number) <= last);
  }, [markers, pricePoints]);

  // Create chart once
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: colors.base03 },
        textColor: colors.base0,
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: colors.base02 },
        horzLines: { color: colors.base02 },
      },
      rightPriceScale: { borderColor: colors.base02 },
      timeScale: { borderColor: colors.base02, timeVisible: false },
      crosshair: {
        vertLine: { color: colors.base01, labelBackgroundColor: colors.base02 },
        horzLine: { color: colors.base01, labelBackgroundColor: colors.base02 },
      },
    });
    const series = chart.addSeries(AreaSeries, {
      lineColor: colors.blue,
      topColor: `${colors.blue}55`,
      bottomColor: `${colors.blue}05`,
      lineWidth: 2,
      priceLineVisible: false,
    });
    chartRef.current = chart;
    seriesRef.current = series;
    markersApiRef.current = createSeriesMarkers(series, []);
    return () => {
      markersApiRef.current = null;
      seriesRef.current = null;
      chartRef.current = null;
      chart.remove();
    };
    // Intentionally create once; theme updates apply via applyOptions below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Apply data
  useEffect(() => {
    const series = seriesRef.current;
    const chart = chartRef.current;
    if (!series || !chart) return;
    series.setData(pricePoints.map(({ time, value }) => ({ time, value })));
    chart.timeScale().fitContent();
  }, [pricePoints]);

  // Apply markers
  useEffect(() => {
    markersApiRef.current?.setMarkers(visibleMarkers);
  }, [visibleMarkers]);

  // Theme updates
  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) return;
    chart.applyOptions({
      layout: {
        background: { type: ColorType.Solid, color: colors.base03 },
        textColor: colors.base0,
      },
      grid: {
        vertLines: { color: colors.base02 },
        horzLines: { color: colors.base02 },
      },
      rightPriceScale: { borderColor: colors.base02 },
      timeScale: { borderColor: colors.base02 },
      crosshair: {
        vertLine: { color: colors.base01, labelBackgroundColor: colors.base02 },
        horzLine: { color: colors.base01, labelBackgroundColor: colors.base02 },
      },
    });
    series.applyOptions({
      lineColor: colors.blue,
      topColor: `${colors.blue}55`,
      bottomColor: `${colors.blue}05`,
    });
  }, [colors]);

  const loading = prices.isLoading;
  const error = prices.error;
  const empty = !loading && !error && pricePoints.length === 0;
  const showOverlay = loading || !!error || empty;

  return (
    <div className="rounded border border-sol-base02 bg-sol-base03 p-3">
      <div className="mb-2 flex items-center justify-between gap-2 flex-wrap">
        <div>
          <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">{symbol} price</div>
          <div className="text-sol-base01 text-[10px]">
            {prices.data?.synced_at ? `synced ${prices.data.synced_at}` : "Daily close"}
            {visibleMarkers.length > 0 ? ` · ${visibleMarkers.length} trade marker${visibleMarkers.length === 1 ? "" : "s"}` : ""}
          </div>
        </div>
        <div className="flex gap-1">
          {PRICE_RANGES.map((item) => (
            <button
              key={item.label}
              type="button"
              onClick={() => setRange(item.label)}
              className={`px-1.5 py-0.5 rounded text-[10px] cursor-pointer ${
                range === item.label
                  ? "bg-sol-blue text-sol-base03"
                  : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
      <div className="relative h-64 w-full">
        <div ref={containerRef} className={`absolute inset-0 ${showOverlay ? "invisible" : ""}`} />
        {loading ? (
          <div className="absolute inset-0 flex items-center justify-center text-sol-base01 italic">Loading price history...</div>
        ) : error ? (
          <div className="absolute inset-0 flex items-center justify-center text-sol-red">Error loading price history</div>
        ) : empty ? (
          <div className="absolute inset-0 flex items-center justify-center text-sol-base01">No price history</div>
        ) : null}
      </div>
    </div>
  );
}

// --- Container -------------------------------------------------------------

export interface TickerViewProps {
  symbol: string;
  vmName?: string | null;
  onSymbolChange?: (symbol: string) => void;
}

export default function TickerView({ symbol, vmName, onSymbolChange }: TickerViewProps) {
  const colors = useThemeColors();
  const [tab, setTab] = useState<MetricTab>("overview");
  const [input, setInput] = useState(symbol);
  useEffect(() => { setInput(symbol); }, [symbol]);

  const normalized = (symbol || "").trim().toUpperCase();

  const fundParams = new URLSearchParams({ symbol: normalized });
  if (vmName) fundParams.set("vm_name", vmName);
  const fundamentals = useSWR<FinanceEnvelope<FundamentalsData>>(
    normalized ? `${API}/api/finance/fundamentals?${fundParams.toString()}` : null,
    fetcher,
    { revalidateOnFocus: false },
  );

  const metrics = fundamentals.data?.data?.metrics;
  const overviewName = (fundamentals.data?.data?.overview?.Name as string | undefined) || null;
  const exchange = (fundamentals.data?.data?.overview?.Exchange as string | undefined) || null;

  const submitSymbol = useCallback((event?: FormEvent) => {
    event?.preventDefault();
    const next = input.trim().toUpperCase();
    if (!next || next === normalized) return;
    onSymbolChange?.(next);
  }, [input, normalized, onSymbolChange]);

  if (!normalized) {
    return (
      <div className="h-full overflow-auto p-4">
        <form onSubmit={submitSymbol} className="flex items-center gap-2 max-w-md">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value.toUpperCase())}
            placeholder="Enter ticker (e.g. NVDA)"
            className="flex-1 px-2 py-1.5 rounded text-sm bg-sol-base02 text-sol-base1 border border-sol-base01 outline-none placeholder:text-sol-base01 font-mono"
          />
          <button type="submit" className="px-3 py-1.5 rounded text-sm bg-sol-blue text-sol-base03 cursor-pointer">
            Analyze
          </button>
        </form>
        <p className="text-sol-base01 text-sm italic mt-4">No ticker selected. Type a symbol above, or open Analyze from Holdings / Transactions.</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto">
      <div className="sticky top-0 z-10 bg-sol-base03/95 backdrop-blur border-b border-sol-base02 px-3 py-2 flex items-center gap-3 flex-wrap">
        <form onSubmit={submitSymbol} className="flex items-center gap-1.5">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value.toUpperCase())}
            className="w-28 px-2 py-1 rounded text-sm bg-sol-base02 text-sol-base1 border border-sol-base01 outline-none font-mono uppercase"
            aria-label="Ticker symbol"
          />
          <button type="submit" className="px-2 py-1 rounded text-xs bg-sol-base02 text-sol-base01 hover:text-sol-base0 cursor-pointer">
            Go
          </button>
        </form>
        <div className="min-w-0">
          <div className="text-sol-base1 font-medium text-sm truncate">
            {normalized}
            {overviewName ? <span className="text-sol-base01 font-normal"> · {overviewName}</span> : null}
          </div>
          <div className="text-sol-base01 text-[10px]">
            {exchange || "Ticker analysis"}
            {fundamentals.data?.source ? ` · ${fundamentals.data.source}` : ""}
            {fundamentals.data?.fetched_at ? ` · fetched ${fundamentals.data.fetched_at}` : ""}
          </div>
        </div>
        <div className="ml-auto flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`px-2 py-1 rounded text-xs cursor-pointer ${
                tab === t.id
                  ? "bg-sol-blue text-sol-base03"
                  : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="p-3 space-y-3">
        <TickerChart symbol={normalized} vmName={vmName} colors={colors} />

        <div className="rounded border border-sol-base02 bg-sol-base03 p-3">
          {fundamentals.isLoading ? (
            <p className="text-sol-base01 italic text-sm">Loading fundamentals...</p>
          ) : fundamentals.error ? (
            <p className="text-sol-red text-sm">Error loading fundamentals</p>
          ) : !metrics ? (
            <p className="text-sol-base01 text-sm italic">No fundamentals data</p>
          ) : tab === "overview" ? (
            <TickerOverviewTab metrics={metrics} />
          ) : tab === "financial" ? (
            <TickerFinancialTab metrics={metrics} />
          ) : tab === "earnings" ? (
            <TickerEarningsTab metrics={metrics} />
          ) : (
            <TickerAnalysisTab metrics={metrics} />
          )}
        </div>
      </div>
    </div>
  );
}
