import { Fragment, useEffect, useRef, useState, useMemo, type ReactNode } from "react";
import useSWR from "swr";
import { API, authFetch, jsonFetcher as fetcher } from "../api";
import {
  LineChart, Line, BarChart, Bar, ComposedChart, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, PieChart, Pie, Cell,
} from "recharts";

interface AccountNode {
  account: string;
  balance: Record<string, number>;
  children: AccountNode[];
}

interface BalanceSheetData {
  assets: AccountNode;
  liabilities: AccountNode;
}

interface IncomeStatementData {
  income: AccountNode;
  expenses: AccountNode;
}

interface BalanceSheetHistoryItem {
  period: string;
  assets: Record<string, number>;
  liabilities: Record<string, number>;
}

interface BalanceSheetPositionsHistoryItem {
  period: string;
  positions: Record<string, Record<string, number>>;
  total?: Record<string, number>;
  risky?: Record<string, number>;
}

interface IncomeStatementHistoryItem {
  period: string;
  income: Record<string, number>;
  expenses: Record<string, number>;
}

interface HoldingAmount {
  number: number;
  currency: string;
}

interface HoldingRow {
  units: HoldingAmount | [];
  average_cost: HoldingAmount | number | null;
  price: HoldingAmount | number | null;
  book_value: HoldingAmount | [];
  market_value: HoldingAmount | [];
  allocation_pct?: number | null;
  unrealized_profit_pct: number | null;
  is_cash?: boolean;
  price_as_of?: string | null;
}

interface HoldingTotalRow {
  book_value: HoldingAmount | [];
  market_value: HoldingAmount | [];
  unrealized_profit_pct: number | null;
}

interface HoldingPosition {
  snapshot_date: string;
  symbol: string;
  quantity: number;
  average_cost: number | null;
  price: number | null;
  book_value: number | null;
  market_value: number | null;
  allocation_pct?: number | null;
  allocation_base_currency?: string;
  market_value_base?: number | null;
  unrealized_profit_pct: number | null;
  cost_currency: string;
  is_cash: boolean;
  price_as_of?: string | null;
}

interface TransactionAmount {
  amount: number;
  currency: string;
}

interface TransactionRow {
  transaction_date: string;
  entry_id?: string;
  symbol: string;
  side: string;
  quantity: number | TransactionAmount[] | null;
  price: number | null;
  price_currency: string;
  amount: number | TransactionAmount[] | null;
  amount_currency?: string;
  commission: number | null;
  commission_currency: string;
  payee: string;
  narration: string;
}

interface FinancePriceRow {
  symbol: string;
  price_date: string;
  price: number;
  currency: string;
}

type Tab = "balance-sheet" | "income-statement" | "holdings" | "transactions" | "fire";

interface FireProgressData {
  net_worth_usd: number;
  target_usd: number;
  gap_usd: number;
  progress_pct: number | null;
  ytd_income_usd: number;
  ytd_expense_usd: number;
  ytd_savings_rate: number | null;
  monthly_expense_usd: number;
  withdrawal_rate: number;
  projected_months_to_target: number | null;
  projected_date: string | null;
  config_source: "file" | "default" | "db" | "config" | "position" | "fire_target";
}

interface FinanceEnvelope<T> {
  data: T;
  synced_at: string;
  source: "cache" | "live" | "sync" | "cli" | "db" | "derived" | "partial";
}

function useFinanceData<T>(key: string | null) {
  return useSWR<T>(key, fetcher, { revalidateOnFocus: false });
}

function useFinanceEnvelope<T>(key: string | null) {
  return useSWR<FinanceEnvelope<T>>(key, fetcher, { revalidateOnFocus: false });
}

function isAbortError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const maybeError = error as { name?: unknown; message?: unknown };
  return maybeError.name === "AbortError" || (typeof maybeError.message === "string" && maybeError.message.toLowerCase().includes("abort"));
}

// Solarized dark colors
const SOL = {
  base03: "#002b36",
  base02: "#073642",
  base01: "#586e75",
  base0: "#839496",
  base1: "#93a1a1",
  blue: "#268bd2",
  red: "#dc322f",
  green: "#859900",
  yellow: "#b58900",
  cyan: "#2aa198",
  magenta: "#d33682",
  violet: "#6c71c4",
  orange: "#cb4b16",
};

function formatAmount(amount: number): string {
  return (amount === 0 ? 0 : amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatPeriodLabel(period: string, fullYear = true): string {
  const [year, month] = period.split("-");
  if (!month) return year;
  if (month.startsWith("Q")) return `${month} ${year}`;
  if (month.startsWith("W")) return `${month} ${year.slice(2)}`;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[parseInt(month, 10) - 1]} ${fullYear ? year : year.slice(2)}`;
}

function totalPositionValue(positions: Record<string, Record<string, number>>): number {
  return Object.values(positions).reduce((sum, balance) => sum + positionValue(balance), 0);
}

function riskyPeriodValue(item: BalanceSheetPositionsHistoryItem): number {
  return positionValue(item.risky);
}

function totalPeriodValue(item: BalanceSheetPositionsHistoryItem): number {
  return positionValue(item.total);
}

function formatCompactUsd(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1_000_000) return `${sign}${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}${(abs / 1_000).toFixed(0)}k`;
  return `${sign}${abs.toFixed(0)}`;
}

type PriceRange = "1M" | "3M" | "1Y" | "YTD" | "ALL";

const PRICE_RANGES: Array<{ label: PriceRange; value: string }> = [
  { label: "1M", value: "1M" },
  { label: "3M", value: "3M" },
  { label: "1Y", value: "1Y" },
  { label: "YTD", value: "YTD" },
  { label: "ALL", value: "" },
];

function formatPriceDate(date: string): string {
  const [year, month, day] = date.split("-");
  if (!year || !month || !day) return date;
  return `${month}/${day}`;
}

function shortName(account: string): string {
  const parts = account.split(":");
  return parts[parts.length - 1] || account;
}

function totalBalance(node: AccountNode): Record<string, number> {
  const totals: Record<string, number> = { ...node.balance };
  for (const child of node.children) {
    const childTotals = totalBalance(child);
    for (const [cur, amt] of Object.entries(childTotals)) {
      totals[cur] = (totals[cur] || 0) + amt;
    }
  }
  return totals;
}

function BalanceDisplay({ balance }: { balance: Record<string, number> }) {
  const entries = Object.entries(balance).filter(([, v]) => Math.abs(v) > 0.005);
  if (entries.length === 0) return null;
  return (
    <span className="text-sol-base0 tabular-nums">
      {entries.map(([cur, amt], i) => (
        <span key={cur}>
          {i > 0 && ", "}
          <span>{formatAmount(amt)}</span>
          <span className="text-sol-base01 ml-1 text-xs">{cur}</span>
        </span>
      ))}
    </span>
  );
}

function AccountRow({ node, depth = 0 }: { node: AccountNode; depth?: number }) {
  const [expanded, setExpanded] = useState(depth < 2);
  const hasChildren = node.children.length > 0;
  const totals = useMemo(() => totalBalance(node), [node]);

  return (
    <>
      <tr className="hover:bg-sol-base02/50 group">
        <td
          className="py-0.5 cursor-pointer"
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
          onClick={() => setExpanded(!expanded)}
        >
          <span className="inline-block w-4 text-center text-sol-base01 text-xs">
            {hasChildren ? (expanded ? "\u25BC" : "\u25B6") : ""}
          </span>
          <span className="text-sol-base1 ml-1">{shortName(node.account)}</span>
        </td>
        <td className="py-0.5 text-right pr-3">
          <BalanceDisplay balance={totals} />
        </td>
      </tr>
      {expanded && node.children.map((child) => (
        <AccountRow key={child.account} node={child} depth={depth + 1} />
      ))}
    </>
  );
}

function AccountTree({ root, title }: { root: AccountNode; title: string }) {
  const totals = useMemo(() => totalBalance(root), [root]);
  return (
    <div className="mb-4">
      <div className="flex items-center justify-between px-3 py-1.5 bg-sol-base02/50 border-b border-sol-base02">
        <span className="text-sol-base1 font-medium text-xs uppercase tracking-wide">{title}</span>
        <BalanceDisplay balance={totals} />
      </div>
      <table className="w-full text-sm">
        <tbody>
          {root.children.map((child) => (
            <AccountRow key={child.account} node={child} depth={0} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EquitySummary({ assets, liabilities }: { assets: AccountNode; liabilities: AccountNode }) {
  const equity = useMemo(() => {
    const a = totalBalance(assets);
    const l = totalBalance(liabilities);
    const result: Record<string, number> = {};
    for (const [cur, amt] of Object.entries(a)) {
      result[cur] = (result[cur] || 0) + amt;
    }
    for (const [cur, amt] of Object.entries(l)) {
      result[cur] = (result[cur] || 0) + amt;
    }
    return result;
  }, [assets, liabilities]);

  return (
    <div className="mb-4">
      <div className="flex items-center justify-between px-3 py-1.5 bg-sol-base02/50 border-b border-sol-base02">
        <span className="text-sol-base1 font-medium text-xs uppercase tracking-wide">Equity (Assets + Liabilities)</span>
        <BalanceDisplay balance={equity} />
      </div>
    </div>
  );
}

function isValidAmount(v: unknown): v is HoldingAmount {
  return v != null && typeof v === "object" && !Array.isArray(v) && "number" in v;
}

type HoldingSortKey = "asset" | "units" | "avg_cost" | "price" | "book_value" | "market_value" | "allocation" | "pnl";
type SortDir = "asc" | "desc";

function getNumericVal(v: HoldingAmount | number | null | []): number {
  if (v == null || Array.isArray(v)) return 0;
  return typeof v === "number" ? v : v.number;
}

function holdingSortValue(h: HoldingRow, key: HoldingSortKey, totalMarketValue = 0): string | number {
  switch (key) {
    case "asset": return (h.units as HoldingAmount).currency;
    case "units": return (h.units as HoldingAmount).number;
    case "avg_cost": return getNumericVal(h.average_cost);
    case "price": return getNumericVal(h.price);
    case "book_value": return getNumericVal(h.book_value);
    case "market_value": return getNumericVal(h.market_value);
    case "allocation": return h.allocation_pct ?? (totalMarketValue ? getNumericVal(h.market_value) / totalMarketValue : 0);
    case "pnl": return h.unrealized_profit_pct ?? 0;
  }
}

function SortableHeader({ label, sortKey, currentKey, dir, onSort, align }: {
  label: string; sortKey: HoldingSortKey; currentKey: HoldingSortKey; dir: SortDir;
  onSort: (key: HoldingSortKey) => void; align: "left" | "right";
}) {
  const active = currentKey === sortKey;
  return (
    <th
      className={`py-1 px-3 font-medium cursor-pointer select-none hover:text-sol-base1 ${align === "left" ? "text-left" : "text-right"}`}
      onClick={() => onSort(sortKey)}
    >
      {label} <span className="text-[10px]">{active ? (dir === "asc" ? "\u25B2" : "\u25BC") : ""}</span>
    </th>
  );
}

function toHoldingRows(positions: HoldingPosition[]): HoldingRow[] {
  return positions.map((row) => ({
    units: { number: row.quantity, currency: row.symbol },
    average_cost: row.average_cost,
    price: row.price,
    book_value: row.book_value == null ? [] : { number: row.book_value, currency: row.cost_currency },
    market_value: row.market_value == null ? [] : { number: row.market_value, currency: row.cost_currency },
    allocation_pct: row.allocation_pct,
    unrealized_profit_pct: row.unrealized_profit_pct,
    is_cash: row.is_cash,
    price_as_of: row.price_as_of,
  }));
}

function holdingTotals(rows: HoldingRow[]): HoldingTotalRow[] {
  return recomputeTotals(rows, []);
}

function holdingBaseValue(row: HoldingPosition): number {
  if (row.market_value_base != null) return row.market_value_base;
  return row.market_value ?? 0;
}

function riskyAllocationSummary(allPositions?: HoldingPosition[], riskyPositions?: HoldingPosition[]) {
  if (!allPositions || !riskyPositions) return null;
  const total = allPositions.reduce((sum, row) => sum + Math.max(0, holdingBaseValue(row)), 0);
  const risky = riskyPositions.reduce((sum, row) => sum + Math.max(0, holdingBaseValue(row)), 0);
  return total > 0 ? { risky, total, ratio: risky / total } : null;
}

function RiskyAllocationSummary({ allPositions, riskyPositions, loading }: { allPositions?: HoldingPosition[]; riskyPositions?: HoldingPosition[]; loading: boolean }) {
  const summary = useMemo(() => riskyAllocationSummary(allPositions, riskyPositions), [allPositions, riskyPositions]);
  const currency = allPositions?.find((row) => row.market_value_base != null)?.allocation_base_currency ?? "USD";

  return (
    <div className="rounded border border-sol-base02 bg-sol-base02/40 px-3 py-2 text-xs">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sol-base1 font-medium uppercase tracking-wide">Risky Allocation</div>
          <div className="text-sol-base01 text-[10px]">Risky assets / total holdings</div>
        </div>
        <div className="text-right tabular-nums">
          {loading ? (
            <div className="text-sol-base01 italic">Loading...</div>
          ) : summary ? (
            <>
              <div className="text-sol-blue text-lg font-semibold">{(summary.ratio * 100).toFixed(1)}%</div>
              <div className="text-sol-base01 text-[10px]">{formatAmount(summary.risky)} / {formatAmount(summary.total)} {currency}</div>
            </>
          ) : (
            <div className="text-sol-base01">—</div>
          )}
        </div>
      </div>
    </div>
  );
}

function formatRelativeTime(iso?: string): string {
  if (!iso) return "not synced";
  const ts = new Date(iso).getTime();
  if (!Number.isFinite(ts)) return iso;
  const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function recomputeTotals(rows: HoldingRow[], originalTotals: HoldingTotalRow[]): HoldingTotalRow[] {
  // Group by market_value currency, mirroring how the API groups totals.
  const byCurrency = new Map<string, { book: number; market: number }>();
  for (const r of rows) {
    if (!isValidAmount(r.market_value)) continue;
    const cur = r.market_value.currency;
    const entry = byCurrency.get(cur) || { book: 0, market: 0 };
    entry.market += r.market_value.number;
    if (isValidAmount(r.book_value) && r.book_value.currency === cur) {
      entry.book += r.book_value.number;
    }
    byCurrency.set(cur, entry);
  }
  // Preserve currency order from the API's totals list when possible.
  const ordered: string[] = [];
  for (const t of originalTotals) {
    const cur = isValidAmount(t.market_value) ? t.market_value.currency : (isValidAmount(t.book_value) ? t.book_value.currency : null);
    if (cur && byCurrency.has(cur) && !ordered.includes(cur)) ordered.push(cur);
  }
  for (const cur of byCurrency.keys()) {
    if (!ordered.includes(cur)) ordered.push(cur);
  }
  return ordered.map((cur) => {
    const e = byCurrency.get(cur)!;
    const pct = e.book !== 0 ? ((e.market - e.book) / e.book) * 100 : null;
    return {
      book_value: { number: e.book, currency: cur } as HoldingAmount,
      market_value: { number: e.market, currency: cur } as HoldingAmount,
      unrealized_profit_pct: pct,
    };
  });
}

function liveQuotesLabel(rows: HoldingRow[]): string | null {
  const times = rows
    .map((row) => row.price_as_of)
    .filter((value): value is string => !!value)
    .map((value) => new Date(value).getTime())
    .filter(Number.isFinite);
  if (!times.length) return null;
  const oldest = new Date(Math.min(...times)).toISOString();
  const newest = new Date(Math.max(...times)).toISOString();
  const oldestLabel = formatRelativeTime(oldest);
  const newestLabel = formatRelativeTime(newest);
  return oldestLabel === newestLabel ? `live quotes as of ${oldestLabel}` : `live quotes as of ${oldestLabel}–${newestLabel}`;
}

function HoldingsTable({ holdings, totals, syncedAt, riskyOnly, onRiskyOnlyChange, vmName }: { holdings: HoldingRow[]; totals: HoldingTotalRow[]; syncedAt?: string; riskyOnly: boolean; onRiskyOnlyChange: (value: boolean) => void; vmName?: string | null }) {
  const [sortKey, setSortKey] = useState<HoldingSortKey>(() => (localStorage.getItem("holdings-sort-key") as HoldingSortKey) || "market_value");
  const [sortDir, setSortDir] = useState<SortDir>(() => (localStorage.getItem("holdings-sort-dir") as SortDir) || "desc");
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);
  const handleSort = (key: HoldingSortKey) => {
    if (key === sortKey) {
      const next = sortDir === "asc" ? "desc" : "asc";
      setSortDir(next);
      localStorage.setItem("holdings-sort-dir", next);
    } else {
      const next = key === "asset" ? "asc" : "desc";
      setSortKey(key); setSortDir(next);
      localStorage.setItem("holdings-sort-key", key);
      localStorage.setItem("holdings-sort-dir", next);
    }
  };

  const toggleRiskyOnly = () => {
    const next = !riskyOnly;
    localStorage.setItem("holdings-risky-only", next ? "1" : "0");
    onRiskyOnlyChange(next);
  };

  const valid = useMemo(() => holdings.filter((h) => isValidAmount(h.units)), [holdings]);
  const filtered = valid;
  const realtimeLabel = useMemo(() => liveQuotesLabel(filtered), [filtered]);

  const totalMarketValue = useMemo(
    () => valid.reduce((sum, row) => sum + getNumericVal(row.market_value), 0),
    [valid],
  );

  const sorted = useMemo(() => {
    const copy = [...filtered];
    copy.sort((a, b) => {
      const av = holdingSortValue(a, sortKey, totalMarketValue);
      const bv = holdingSortValue(b, sortKey, totalMarketValue);
      let cmp: number;
      if (typeof av === "string" && typeof bv === "string") cmp = av.localeCompare(bv);
      else cmp = (av as number) - (bv as number);
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [filtered, sortKey, sortDir, totalMarketValue]);

  const displayTotals = useMemo(() => recomputeTotals(filtered, totals), [filtered, totals]);

  const hp = { currentKey: sortKey, dir: sortDir, onSort: handleSort };

  const toggleExpanded = (row: HoldingRow) => {
    if (row.is_cash || !isValidAmount(row.units)) return;
    const symbol = row.units.currency;
    setExpandedSymbol((current) => current === symbol ? null : symbol);
  };

  return (
    <div className="mb-4">
      <div className="px-3 py-1.5 bg-sol-base02/50 border-b border-sol-base02 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sol-base1 font-medium text-xs uppercase tracking-wide">Holdings · synced {formatRelativeTime(syncedAt)}</span>
          {realtimeLabel ? <span className="rounded bg-sol-base02 px-1.5 py-0.5 text-[10px] text-sol-base01">{realtimeLabel}</span> : null}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={toggleRiskyOnly}
            className={`px-1.5 py-0.5 rounded text-[10px] cursor-pointer ${
              riskyOnly
                ? "bg-sol-blue text-sol-base03"
                : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"
            }`}
            title="Hide cash and BOXX"
          >
            Risky only
          </button>
        </div>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-sol-base01 text-xs border-b border-sol-base02">
            <SortableHeader label="Asset" sortKey="asset" align="left" {...hp} />
            <SortableHeader label="Units" sortKey="units" align="right" {...hp} />
            <SortableHeader label="Avg Cost" sortKey="avg_cost" align="right" {...hp} />
            <SortableHeader label="Price" sortKey="price" align="right" {...hp} />
            <SortableHeader label="Book Value" sortKey="book_value" align="right" {...hp} />
            <SortableHeader label="Market Value" sortKey="market_value" align="right" {...hp} />
            <SortableHeader label="Allocation" sortKey="allocation" align="right" {...hp} />
            <SortableHeader label="P&L %" sortKey="pnl" align="right" {...hp} />
          </tr>
        </thead>
        <tbody>
          {sorted.map((h, i) => {
            if (!isValidAmount(h.units)) return null;
            const symbol = h.units.currency;
            const isExpanded = expandedSymbol === symbol;
            const canExpand = !h.is_cash;
            const priceAsOf = h.price_as_of || null;
            return (
              <Fragment key={`${symbol}-${i}`}>
                <tr
                  className={`hover:bg-sol-base02/50 ${canExpand ? "cursor-pointer" : ""}`}
                  onClick={() => toggleExpanded(h)}
                  title={canExpand ? `Show ${symbol} price history` : undefined}
                >
                  <td className="py-0.5 px-3 text-sol-base1">
                    <span className="inline-block w-4 text-center text-sol-base01 text-xs">{canExpand ? (isExpanded ? "\u25BC" : "\u25B6") : ""}</span>
                    <span className="ml-1">{symbol}</span>
                  </td>
                  <td className="py-0.5 px-3 text-right tabular-nums text-sol-base0">{formatAmount(h.units.number)}</td>
                  <td className="py-0.5 px-3 text-right tabular-nums text-sol-base0">
                    {h.average_cost != null ? formatAmount(typeof h.average_cost === "number" ? h.average_cost : h.average_cost.number) : "—"}
                  </td>
                  <td className="py-0.5 px-3 text-right tabular-nums text-sol-base0" title={priceAsOf ? `Realtime quote as of ${priceAsOf}` : undefined}>
                    {h.price != null ? (
                      priceAsOf ? (
                        <div>
                          <div>{formatAmount(typeof h.price === "number" ? h.price : h.price.number)}</div>
                          <div className="text-[10px] text-sol-base01">as of {formatRelativeTime(priceAsOf)}</div>
                        </div>
                      ) : formatAmount(typeof h.price === "number" ? h.price : h.price.number)
                    ) : "—"}
                  </td>
                  <td className="py-0.5 px-3 text-right tabular-nums text-sol-base0">
                    {isValidAmount(h.book_value) ? <>{formatAmount(h.book_value.number)} <span className="text-sol-base01 text-xs">{h.book_value.currency}</span></> : "—"}
                  </td>
                  <td className="py-0.5 px-3 text-right tabular-nums text-sol-base0" title={priceAsOf ? "Market value uses live realtime quote" : undefined}>
                    {isValidAmount(h.market_value) ? <>{formatAmount(h.market_value.number)} <span className="text-sol-base01 text-xs">{h.market_value.currency}</span>{priceAsOf ? <> <span className="text-sol-base01 text-[10px]">(live)</span></> : null}</> : "—"}
                  </td>
                  <td className="py-0.5 px-3 text-right tabular-nums text-sol-base0">
                    {h.allocation_pct != null ? `${(h.allocation_pct * 100).toFixed(1)}%` : (totalMarketValue ? `${((getNumericVal(h.market_value) / totalMarketValue) * 100).toFixed(1)}%` : "—")}
                  </td>
                  <td className={`py-0.5 px-3 text-right tabular-nums ${(h.unrealized_profit_pct ?? 0) > 0 ? "text-sol-green" : (h.unrealized_profit_pct ?? 0) < 0 ? "text-sol-red" : "text-sol-base0"}`}>
                    {h.unrealized_profit_pct != null ? <>{h.unrealized_profit_pct > 0 ? "+" : ""}{formatAmount(h.unrealized_profit_pct)}%</> : "—"}
                  </td>
                </tr>
                {isExpanded ? (
                  <tr className="border-y border-sol-base02 bg-sol-base03">
                    <td colSpan={8} className="px-3 py-3">
                      <PriceChart symbol={symbol} vmName={vmName} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
          {displayTotals.map((t, i) => {
            const bv = isValidAmount(t.book_value) ? t.book_value : null;
            const mv = isValidAmount(t.market_value) ? t.market_value : null;
            const pct = t.unrealized_profit_pct ?? 0;
            return (
              <tr key={i} className="border-t border-sol-base02 font-medium">
                <td className="py-1 px-3 text-sol-base1" colSpan={4}>Total Stock{displayTotals.length > 1 && bv ? ` (${bv.currency})` : ""}</td>
                <td className="py-1 px-3 text-right tabular-nums text-sol-base0">{bv ? formatAmount(bv.number) : "—"}</td>
                <td className="py-1 px-3 text-right tabular-nums text-sol-base0">{mv ? formatAmount(mv.number) : "—"}</td>
                <td className="py-1 px-3 text-right tabular-nums text-sol-base0">—</td>
                <td className={`py-1 px-3 text-right tabular-nums ${pct > 0 ? "text-sol-green" : pct < 0 ? "text-sol-red" : "text-sol-base0"}`}>
                  {t.unrealized_profit_pct != null ? <>{pct > 0 ? "+" : ""}{formatAmount(pct)}%</> : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

type TransactionSortKey = "date" | "symbol" | "side" | "quantity" | "amount";


function formatTransactionValue(value: number | TransactionAmount[] | null | undefined, currency?: string): ReactNode {
  if (value == null) return "—";
  if (Array.isArray(value)) {
    if (value.length === 0) return "—";
    return value.map((item, index) => (
      <span key={`${item.currency}-${index}`}>
        {index > 0 && ", "}
        {formatAmount(item.amount)} {item.currency && <span className="text-sol-base01 text-xs">{item.currency}</span>}
      </span>
    ));
  }
  return <>{formatAmount(value)} {currency && <span className="text-sol-base01 text-xs">{currency}</span>}</>;
}

function transactionSortValue(row: TransactionRow, key: TransactionSortKey): string | number {
  switch (key) {
    case "date": return row.transaction_date;
    case "symbol": return row.symbol;
    case "side": return row.side;
    case "quantity": return Array.isArray(row.quantity) ? row.quantity.reduce((sum, item) => sum + item.amount, 0) : row.quantity ?? 0;
    case "amount": return Array.isArray(row.amount) ? row.amount.reduce((sum, item) => sum + item.amount, 0) : row.amount ?? 0;
  }
}

function TransactionHeader({ label, sortKey, currentKey, dir, onSort, align }: {
  label: string; sortKey: TransactionSortKey; currentKey: TransactionSortKey; dir: SortDir;
  onSort: (key: TransactionSortKey) => void; align: "left" | "right";
}) {
  const active = currentKey === sortKey;
  return (
    <th className={`py-1 px-3 font-medium cursor-pointer select-none hover:text-sol-base1 ${align === "left" ? "text-left" : "text-right"}`} onClick={() => onSort(sortKey)}>
      {label}{active && <span className="ml-1 text-sol-blue">{dir === "asc" ? "▲" : "▼"}</span>}
    </th>
  );
}

function TransactionsTable({ rows, syncedAt }: { rows: TransactionRow[]; syncedAt?: string }) {
  const [sortKey, setSortKey] = useState<TransactionSortKey>(() => (localStorage.getItem("transactions-sort-key") as TransactionSortKey) || "date");
  const [sortDir, setSortDir] = useState<SortDir>(() => (localStorage.getItem("transactions-sort-dir") as SortDir) || "desc");
  const handleSort = (key: TransactionSortKey) => {
    if (key === sortKey) {
      const next = sortDir === "asc" ? "desc" : "asc";
      setSortDir(next); localStorage.setItem("transactions-sort-dir", next);
    } else {
      const next = key === "date" ? "desc" : "asc";
      setSortKey(key); setSortDir(next);
      localStorage.setItem("transactions-sort-key", key); localStorage.setItem("transactions-sort-dir", next);
    }
  };
  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = transactionSortValue(a, sortKey);
      const bv = transactionSortValue(b, sortKey);
      const cmp = typeof av === "string" && typeof bv === "string" ? av.localeCompare(bv) : (av as number) - (bv as number);
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [rows, sortKey, sortDir]);
  const hp = { currentKey: sortKey, dir: sortDir, onSort: handleSort };
  return (
    <div className="mb-4">
      <div className="px-3 py-1.5 bg-sol-base02/50 border-b border-sol-base02 flex items-center justify-between">
        <span className="text-sol-base1 font-medium text-xs uppercase tracking-wide">Transactions · synced {formatRelativeTime(syncedAt)}</span>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-sol-base01 text-xs border-b border-sol-base02">
            <TransactionHeader label="Date" sortKey="date" align="left" {...hp} />
            <TransactionHeader label="Symbol" sortKey="symbol" align="left" {...hp} />
            <TransactionHeader label="Side" sortKey="side" align="left" {...hp} />
            <TransactionHeader label="Quantity" sortKey="quantity" align="right" {...hp} />
            <th className="py-1 px-3 font-medium text-right">Price</th>
            <TransactionHeader label="Amount" sortKey="amount" align="right" {...hp} />
            <th className="py-1 px-3 font-medium text-left">Notes</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr key={i} className="hover:bg-sol-base02/50">
              <td className="py-0.5 px-3 text-sol-base0 tabular-nums">{row.transaction_date}</td>
              <td className="py-0.5 px-3 text-sol-base1">{row.symbol}</td>
              <td className="py-0.5 px-3 text-sol-base0">{row.side}</td>
              <td className="py-0.5 px-3 text-right tabular-nums text-sol-base0">{formatTransactionValue(row.quantity)}</td>
              <td className="py-0.5 px-3 text-right tabular-nums text-sol-base0">{formatTransactionValue(row.price, row.price_currency)}</td>
              <td className="py-0.5 px-3 text-right tabular-nums text-sol-base0">{formatTransactionValue(row.amount, row.amount_currency)}</td>
              <td className="py-0.5 px-3 text-sol-base0 truncate max-w-md">{row.payee || row.narration}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Granularity = "monthly" | "yearly";
type HoldingsGranularity = "weekly" | "monthly" | "yearly";
const ACCOUNT_COLORS = [SOL.blue, SOL.cyan, SOL.green, SOL.orange, SOL.magenta, SOL.violet, SOL.yellow, SOL.red];

function GranularityToggle({ value, onChange }: { value: Granularity; onChange: (v: Granularity) => void }) {
  return (
    <div className="flex gap-1">
      {(["monthly", "yearly"] as const).map((g) => (
        <button
          key={g}
          onClick={() => onChange(g)}
          className={`px-1.5 py-0.5 rounded text-[10px] cursor-pointer ${
            value === g
              ? "bg-sol-blue text-sol-base03"
              : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"
          }`}
        >
          {g === "monthly" ? "M" : "Y"}
        </button>
      ))}
    </div>
  );
}

function HoldingsModeToggle({ riskyOnly, overTime, onRiskyOnlyChange, onOverTimeChange }: { riskyOnly: boolean; overTime: boolean; onRiskyOnlyChange: (v: boolean) => void; onOverTimeChange: (v: boolean) => void }) {
  return (
    <div className="flex gap-1">
      {([["risky", riskyOnly, onRiskyOnlyChange], ["over time", overTime, onOverTimeChange]] as const).map(([label, checked, onChange]) => (
        <button
          key={label}
          onClick={() => onChange(!checked)}
          className={`px-2 py-0.5 rounded text-xs cursor-pointer ${
            checked
              ? "bg-sol-blue text-sol-base03"
              : "bg-sol-base02 text-sol-base0 hover:text-sol-base1"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function HoldingsGranularityToggle({ value, onChange }: { value: HoldingsGranularity; onChange: (v: HoldingsGranularity) => void }) {
  return (
    <div className="flex gap-1">
      {(["weekly", "monthly", "yearly"] as const).map((g) => (
        <button
          key={g}
          onClick={() => onChange(g)}
          className={`px-1.5 py-0.5 rounded text-[10px] cursor-pointer ${
            value === g
              ? "bg-sol-blue text-sol-base03"
              : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"
          }`}
        >
          {g === "weekly" ? "W" : g === "monthly" ? "M" : "Y"}
        </button>
      ))}
    </div>
  );
}

// --- Chart Components ---

function tooltipLabel(payload: any[] | undefined, fallback?: string): string {
  const rawDate = payload?.[0]?.payload?.rawDate;
  if (rawDate) return rawDate;
  const raw = payload?.[0]?.payload?.rawPeriod;
  if (raw) return formatPeriodLabel(raw, true);
  return fallback ?? "";
}

function ChartTooltipContent({ active, payload, label, formatter, sortByValueDesc = false }: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string; payload?: any }>;
  label?: string;
  formatter?: (value: number) => string;
  sortByValueDesc?: boolean;
}) {
  if (!active || !payload?.length) return null;
  const rows = sortByValueDesc ? [...payload].sort((a, b) => Number(b.value || 0) - Number(a.value || 0)) : payload;
  return (
    <div className="rounded px-2 py-1.5 text-xs" style={{ background: SOL.base02, border: `1px solid ${SOL.base01}` }}>
      <div style={{ color: SOL.base1 }} className="mb-1">{tooltipLabel(payload, label)}</div>
      {rows.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full" style={{ background: p.color }} />
          <span style={{ color: SOL.base0 }}>{p.name}: {formatter ? formatter(p.value) : p.value}</span>
        </div>
      ))}
    </div>
  );
}

function PriceChart({ symbol, vmName }: { symbol: string; vmName?: string | null }) {
  const [range, setRange] = useState<PriceRange>("YTD");
  const time = PRICE_RANGES.find((item) => item.label === range)?.value ?? "YTD";
  const params = new URLSearchParams({ symbol, limit: "1000", time });
  if (vmName) params.set("vm_name", vmName);
  const prices = useFinanceEnvelope<FinancePriceRow[]>(`${API}/api/finance/prices?${params.toString()}`);

  const chartData = useMemo(() =>
    (prices.data?.data ?? []).map((row) => ({
        date: formatPriceDate(row.price_date),
        rawDate: row.price_date,
        price: row.price,
        currency: row.currency,
      })),
    [prices.data?.data]
  );

  const currency = chartData[0]?.currency ?? "";

  return (
    <div className="rounded border border-sol-base02 bg-sol-base03 p-3" onClick={(event) => event.stopPropagation()}>
      <div className="mb-2 flex items-center justify-between">
        <div>
          <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">{symbol} price history</div>
          <div className="text-sol-base01 text-[10px]">{prices.data?.synced_at ? `synced ${formatRelativeTime(prices.data.synced_at)}` : "Daily prices"}</div>
        </div>
        <div className="flex gap-1">
          {PRICE_RANGES.map((item) => (
            <button
              key={item.label}
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
      {prices.isLoading ? (
        <div className="flex h-56 items-center justify-center text-sol-base01 italic">Loading price history...</div>
      ) : prices.error ? (
        <div className="flex h-56 items-center justify-center text-sol-red">Error loading price history</div>
      ) : chartData.length === 0 ? (
        <div className="flex h-56 items-center justify-center text-sol-base01">No price history</div>
      ) : (
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={chartData} margin={{ top: 10, right: 20, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={SOL.base02} />
            <XAxis dataKey="date" tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} minTickGap={20} />
            <YAxis tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} domain={["auto", "auto"]} tickFormatter={(v) => formatAmount(v)} />
            <Tooltip
              content={<ChartTooltipContent formatter={(value) => `${formatAmount(value)} ${currency}`} />}
              labelFormatter={(label) => String(label)}
            />
            <Line type="monotone" dataKey="price" name="Price" stroke={SOL.blue} strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

const HOLDINGS_PIE_COLORS = [SOL.blue, SOL.green, SOL.yellow, SOL.cyan, SOL.magenta, SOL.violet, SOL.orange, SOL.red];

function HoldingsPieTooltip({ active, payload }: {
  active?: boolean;
  payload?: Array<{ payload?: { symbol: string; value: number; currency: string; allocation: number }; color?: string }>;
}) {
  if (!active || !payload?.length) return null;
  const item = payload[0]?.payload;
  if (!item) return null;
  return (
    <div className="rounded px-2 py-1.5 text-xs" style={{ background: SOL.base02, border: `1px solid ${SOL.base01}` }}>
      <div style={{ color: SOL.base1 }} className="mb-1">{item.symbol}</div>
      <div className="flex items-center gap-2">
        <span className="inline-block w-2 h-2 rounded-full" style={{ background: payload[0]?.color ?? SOL.base0 }} />
        <span style={{ color: SOL.base0 }}>{formatAmount(item.value)} {item.currency} · {(item.allocation * 100).toFixed(1)}%</span>
      </div>
    </div>
  );
}

function HoldingsPieChart({ positions }: { positions: HoldingPosition[] }) {
  const chartData = useMemo(() => {
    const rows = positions
      .filter((position) => position.market_value_base != null && position.market_value_base > 0)
      .map((position) => ({
        symbol: position.symbol,
        value: position.market_value_base as number,
        currency: position.allocation_base_currency ?? "USD",
      }))
      .sort((a, b) => b.value - a.value);
    const total = rows.reduce((sum, row) => sum + row.value, 0);
    return total > 0 ? rows.map((row) => ({ ...row, allocation: row.value / total })) : [];
  }, [positions]);

  if (chartData.length === 0) return null;

  return (
    <div className="mb-3">
      <ResponsiveContainer width="100%" height={300}>
        <PieChart margin={{ top: 10, right: 20, left: 20, bottom: 5 }}>
          <Pie
            data={chartData}
            dataKey="value"
            nameKey="symbol"
            cx="50%"
            cy="50%"
            outerRadius={110}
            label={(props) => {
              const payload = props.payload as { symbol?: string; allocation?: number } | undefined;
              return (payload?.allocation ?? 0) >= 0.03 ? (payload?.symbol ?? "") : "";
            }}
            labelLine={false}
            isAnimationActive={false}
          >
            {chartData.map((entry, index) => (
              <Cell key={entry.symbol} fill={HOLDINGS_PIE_COLORS[index % HOLDINGS_PIE_COLORS.length]} />
            ))}
          </Pie>
          <Tooltip content={<HoldingsPieTooltip />} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

function BalanceSheetChart({ data, granularity, onGranularityChange, targetLine }: { data: BalanceSheetHistoryItem[]; granularity: Granularity; onGranularityChange: (v: Granularity) => void; targetLine?: number }) {
  const chartData = useMemo(() =>
    data.map((item) => ({
      period: formatPeriodLabel(item.period),
      rawPeriod: item.period,
      "Net Worth": (item.assets.USD || 0) + (item.liabilities.USD || 0),
    })),
    [data]
  );

  return (
    <div className="relative">
      <div className="absolute top-0 right-2 z-10">
        <GranularityToggle value={granularity} onChange={onGranularityChange} />
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData} margin={{ top: 10, right: 20, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={SOL.base02} />
          <XAxis dataKey="period" tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} />
          <YAxis tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
          <Tooltip content={<ChartTooltipContent formatter={(v) => formatAmount(v) + " USD"} />} />
          {targetLine != null && (
            <ReferenceLine
              y={targetLine}
              stroke={SOL.yellow}
              strokeDasharray="4 4"
              label={{ value: `Target: ${(targetLine / 1000).toFixed(0)}k`, fill: SOL.yellow, fontSize: 11, position: "insideTopRight" }}
            />
          )}
          <Line type="linear" dataKey="Net Worth" stroke={SOL.green} dot={false} strokeWidth={2} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function positionValue(balance: Record<string, number> | undefined): number {
  return balance?.USD || 0;
}

function buildPositionSeries(data: BalanceSheetPositionsHistoryItem[]) {
  const latest = data[data.length - 1];
  const totals = new Map<string, number>();
  for (const item of data) {
    for (const [account, balance] of Object.entries(item.positions)) {
      totals.set(account, Math.max(totals.get(account) || 0, Math.abs(positionValue(balance))));
    }
  }
  const ordered = Array.from(totals.entries())
    .filter(([, value]) => value > 0.005)
    .sort((a, b) => positionValue(latest?.positions[b[0]]) - positionValue(latest?.positions[a[0]]));
  const topAccounts = ordered.slice(0, 7).map(([account]) => account);
  const otherAccounts = ordered.slice(7).map(([account]) => account);
  return otherAccounts.length ? [...topAccounts, "Other"] : topAccounts;
}

function positionChartRows(data: BalanceSheetPositionsHistoryItem[], positions: string[]) {
  return data.map((item) => {
    const total = totalPositionValue(item.positions);
    const unfilteredTotal = totalPeriodValue(item);
    const risky = riskyPeriodValue(item);
    const row: Record<string, string | number> = {
      period: formatPeriodLabel(item.period),
      rawPeriod: item.period,
      Total: total,
      RiskyValue: risky,
      RiskyPct: unfilteredTotal > 0 ? (risky / unfilteredTotal) * 100 : 0,
    };
    for (const account of positions) {
      if (account === "Other") continue;
      row[account] = positionValue(item.positions[account]);
    }
    if (positions.includes("Other")) {
      const named = new Set(positions.filter((account) => account !== "Other"));
      row.Other = Object.entries(item.positions).reduce((sum, [account, balance]) => sum + (named.has(account) ? 0 : positionValue(balance)), 0);
    }
    return row;
  });
}

function positionPeriodTotals(data: BalanceSheetPositionsHistoryItem[]) {
  return Object.fromEntries(data.map((item) => [item.period, totalPositionValue(item.positions)]));
}

function riskyPeriodTotals(data: BalanceSheetPositionsHistoryItem[]) {
  return Object.fromEntries(data.map((item) => [item.period, riskyPeriodValue(item)]));
}

function riskyPeriodPercents(data: BalanceSheetPositionsHistoryItem[]) {
  return Object.fromEntries(data.map((item) => {
    const total = totalPeriodValue(item);
    return [item.period, total > 0 ? (riskyPeriodValue(item) / total) * 100 : 0];
  }));
}

function positionTableRows(data: BalanceSheetPositionsHistoryItem[], positions: string[], sortColumn: string, sortDir: "asc" | "desc") {
  return positions
    .map((position) => ({
      position,
      values: Object.fromEntries(data.map((item) => [item.period, position === "Other"
        ? Object.entries(item.positions).reduce((sum, [name, balance]) => sum + (positions.includes(name) ? 0 : positionValue(balance)), 0)
        : positionValue(item.positions[position])
      ])),
    }))
    .sort((a, b) => {
      const delta = (a.values[sortColumn] || 0) - (b.values[sortColumn] || 0);
      return sortDir === "asc" ? delta : -delta;
    });
}

function AssetsOverTimeTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string; payload?: any; dataKey?: string | number }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const dataPoint = payload[0]?.payload;
  const totalValue = Number(dataPoint?.Total || 0);
  const riskyValue = Number(dataPoint?.RiskyValue || 0);
  const riskyPct = Number(dataPoint?.RiskyPct || 0);
  const rows = payload
    .filter((item) => item.dataKey !== "RiskyPct" && item.name !== "RiskyPct")
    .sort((a, b) => Number(b.value || 0) - Number(a.value || 0));
  return (
    <div className="rounded px-2 py-1.5 text-xs" style={{ background: SOL.base02, border: `1px solid ${SOL.base01}` }}>
      <div style={{ color: SOL.base1 }} className="mb-1">{tooltipLabel(payload, label)}</div>
      <div className="mb-1 flex items-center gap-2">
        <span className="inline-block w-2 h-2 rounded-full" style={{ background: SOL.base1 }} />
        <span style={{ color: SOL.base1, fontWeight: 500 }}>Total: {formatAmount(totalValue)} USD</span>
      </div>
      {rows.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full" style={{ background: p.color }} />
          <span style={{ color: SOL.base0 }}>{p.name}: {formatAmount(p.value)} USD</span>
        </div>
      ))}
      <div className="mt-1 border-t pt-1" style={{ borderColor: SOL.base01 }}>
        <div className="flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full" style={{ background: SOL.yellow }} />
          <span style={{ color: SOL.base1, fontWeight: 500 }}>Risky: {formatAmount(riskyValue)} USD</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full" style={{ background: SOL.yellow }} />
          <span style={{ color: SOL.base0 }}>Risky %: {formatAmount(riskyPct)}%</span>
        </div>
      </div>
    </div>
  );
}

function AssetsOverTimeChart({ data, positions, granularity, onGranularityChange }: { data: BalanceSheetPositionsHistoryItem[]; positions: string[]; granularity: HoldingsGranularity; onGranularityChange: (v: HoldingsGranularity) => void }) {
  const chartData = useMemo(() => positionChartRows(data, positions), [data, positions]);
  const hasData = chartData.some((row) => positions.some((account) => Math.abs(Number(row[account] || 0)) > 0.005));
  const hasRiskyData = data.some((item) => item.risky && totalPositionValue(item.positions) > 0);

  return (
    <div className="relative rounded border border-sol-base02 bg-sol-base03 p-3">
      <div className="absolute top-3 right-3">
        <HoldingsGranularityToggle value={granularity} onChange={onGranularityChange} />
      </div>
      <div className="mb-2">
        <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">Assets over time</div>
        <div className="text-sol-base01 text-[10px]">Transaction-based positions in USD</div>
      </div>
      {!hasData ? (
        <div className="flex h-56 items-center justify-center text-sol-base01">No history yet</div>
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={chartData} margin={{ top: 24, right: 20, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={SOL.base02} />
            <XAxis dataKey="period" tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} />
            <YAxis yAxisId="assets" tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
            {hasRiskyData && <YAxis yAxisId="risky" orientation="right" domain={[0, 100]} tick={{ fill: SOL.yellow, fontSize: 11 }} stroke={SOL.base02} tickFormatter={(v) => `${v}%`} />}
            <Tooltip content={<AssetsOverTimeTooltip />} cursor={{ fill: "rgba(147, 161, 161, 0.15)" }} />
            {positions.map((account, index) => {
              return (
                <Bar key={account} dataKey={account} yAxisId="assets" stackId="assets" fill={ACCOUNT_COLORS[index % ACCOUNT_COLORS.length]} isAnimationActive={false} />
              );
            })}
            {hasRiskyData && <Line type="linear" dataKey="RiskyPct" yAxisId="risky" stroke={SOL.yellow} strokeDasharray="4 4" dot={false} strokeWidth={2} isAnimationActive={false} />}
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

function AssetsOverTimePerAccountTable({ data, positions }: { data: BalanceSheetPositionsHistoryItem[]; positions: string[] }) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const latestPeriod = data[data.length - 1]?.period || "";
  const periodKey = useMemo(() => data.map((item) => item.period).join("|"), [data]);
  const [sortColumn, setSortColumn] = useState(latestPeriod);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const effectiveSortColumn = data.some((item) => item.period === sortColumn) ? sortColumn : latestPeriod;
  const rows = useMemo(() => positionTableRows(data, positions, effectiveSortColumn, sortDir), [data, positions, effectiveSortColumn, sortDir]);
  const totals = useMemo(() => positionPeriodTotals(data), [data]);
  const riskyTotals = useMemo(() => riskyPeriodTotals(data), [data]);
  const riskyPercents = useMemo(() => riskyPeriodPercents(data), [data]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;

    const frame = requestAnimationFrame(() => {
      container.scrollLeft = container.scrollWidth - container.clientWidth;
    });

    return () => cancelAnimationFrame(frame);
  }, [periodKey]);

  const handleSort = (period: string) => {
    if (period === effectiveSortColumn) {
      setSortDir((dir) => dir === "desc" ? "asc" : "desc");
    } else {
      setSortColumn(period);
      setSortDir("desc");
    }
  };

  return (
    <div className="rounded border border-sol-base02 bg-sol-base03 overflow-hidden">
      <div className="border-b border-sol-base02 px-3 py-2">
        <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">Assets history</div>
        <div className="text-sol-base01 text-[10px]">Rows are symbols and cash currencies; columns are periods</div>
      </div>
      {data.length === 0 || positions.length === 0 ? (
        <div className="px-3 py-8 text-center text-sol-base01">No history yet</div>
      ) : (
        <div ref={scrollRef} className="overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead>
              <tr className="text-sol-base01 border-b border-sol-base02 bg-sol-base02/50">
                <th className="sticky left-0 z-10 bg-sol-base02 text-left font-normal py-1 px-3 whitespace-nowrap">Position</th>
                {data.map((item) => (
                  <th key={item.period} className="text-right font-normal py-1 px-3 whitespace-nowrap">
                    <button onClick={() => handleSort(item.period)} className="cursor-pointer hover:text-sol-base0">
                      {formatPeriodLabel(item.period)} {effectiveSortColumn === item.period ? (sortDir === "desc" ? "↓" : "↑") : ""}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.position} className="hover:bg-sol-base02/50">
                  <td className="sticky left-0 z-10 bg-sol-base03 py-0.5 px-3 text-sol-base0 whitespace-nowrap">{row.position}</td>
                  {data.map((item) => (
                    <td key={item.period} className="py-0.5 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap">{formatAmount(row.values[item.period] || 0)}</td>
                  ))}
                </tr>
              ))}
              <tr className="border-t border-sol-base02 bg-sol-base02/40 font-medium">
                <td className="sticky left-0 z-10 bg-sol-base02 py-1 px-3 text-sol-base1 whitespace-nowrap">Total</td>
                {data.map((item) => (
                  <td key={item.period} className="py-1 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap">{formatAmount(totals[item.period] || 0)}</td>
                ))}
              </tr>
              <tr className="bg-sol-base02/40 font-medium">
                <td className="sticky left-0 z-10 bg-sol-base02 py-1 px-3 text-sol-base0 whitespace-nowrap">Risky</td>
                {data.map((item) => (
                  <td key={item.period} className="py-1 px-3 text-right tabular-nums text-sol-base0 whitespace-nowrap">{formatAmount(riskyTotals[item.period] || 0)}</td>
                ))}
              </tr>
              <tr className="bg-sol-base02/40 font-medium">
                <td className="sticky left-0 z-10 bg-sol-base02 py-1 px-3 text-sol-base0 whitespace-nowrap">Risky %</td>
                {data.map((item) => (
                  <td key={item.period} className="py-1 px-3 text-right tabular-nums text-sol-base0 whitespace-nowrap">{formatAmount(riskyPercents[item.period] || 0)}%</td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function AssetsOverTimeView({ vmName, riskyOnly, time, granularity, onGranularityChange, controls }: { vmName?: string | null; riskyOnly: boolean; time: string; granularity: HoldingsGranularity; onGranularityChange: (v: HoldingsGranularity) => void; controls: ReactNode }) {
  const vmQuery = vmName ? `&vm_name=${encodeURIComponent(vmName)}` : "";
  const key = `${API}/api/finance/balance-sheet?history=true&breakdown=positions&granularity=${granularity}&convert=USD&risky_only=${riskyOnly ? "true" : "false"}&time=${encodeURIComponent(time)}${vmQuery}`;
  const history = useFinanceEnvelope<BalanceSheetPositionsHistoryItem[]>(key);
  const data = history.data?.data || [];
  const positions = useMemo(() => buildPositionSeries(data), [data]);
  const showError = !!history.error && !isAbortError(history.error) && !history.data && !history.isLoading && !history.isValidating;

  return (
    <div className="space-y-3">
      {history.isLoading ? (
        <p className="text-sol-base01 italic px-3">Loading assets history...</p>
      ) : showError ? (
        <p className="text-sol-red px-3">Error loading assets history</p>
      ) : (
        <>
          <AssetsOverTimeChart data={data} positions={positions} granularity={granularity} onGranularityChange={onGranularityChange} />
          <div className="flex justify-end px-2">
            {controls}
          </div>
          <AssetsOverTimePerAccountTable data={data} positions={positions} />
        </>
      )}
    </div>
  );
}

// --- FIRE Progress View ---

function formatUsd(amount: number): string {
  const abs = Math.abs(amount);
  const sign = amount < 0 ? "-" : "";
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(0)}`;
}

function FireMetricCard({ title, value, sub, valueColor }: { title: string; value: string; sub?: string; valueColor?: string }) {
  return (
    <div className="bg-sol-base02/50 rounded p-3 border border-sol-base02">
      <div className="text-sol-base01 text-[10px] uppercase tracking-wide mb-1">{title}</div>
      <div className={`text-xl font-medium tabular-nums ${valueColor ?? "text-sol-base1"}`}>{value}</div>
      {sub && <div className="text-sol-base01 text-xs mt-1">{sub}</div>}
    </div>
  );
}

function FireProgressView({ data }: { data: FireProgressData }) {
  const pct = data.progress_pct ?? 0;
  const clampedPct = Math.max(0, Math.min(100, pct));
  const reached = data.gap_usd <= 0;
  const ytdNet = data.ytd_income_usd - data.ytd_expense_usd;
  const monthsElapsed = (() => {
    const today = new Date();
    const start = new Date(today.getFullYear(), 0, 1);
    return Math.max((today.getTime() - start.getTime()) / (1000 * 60 * 60 * 24 * 30.44), 1 / 30.44);
  })();
  const avgMonthlySavings = ytdNet / monthsElapsed;

  return (
    <div className="space-y-4">
      {/* Headline */}
      <div className="text-center py-3">
        <div className="text-sol-base01 text-xs uppercase tracking-wide mb-1">
          {reached ? "FIRE Reached" : "Distance to FIRE"}
        </div>
        <div className={`text-3xl font-medium tabular-nums ${reached ? "text-sol-green" : "text-sol-base1"}`}>
          {reached ? "🎉 Done" : formatUsd(data.gap_usd)}
        </div>
        <div className="text-sol-base0 text-sm mt-1 tabular-nums">
          {clampedPct.toFixed(2)}% complete
        </div>
      </div>

      {/* Progress bar */}
      <div className="px-3">
        <div className="flex items-center justify-between text-xs text-sol-base01 mb-1 tabular-nums">
          <span>{formatUsd(data.net_worth_usd)}</span>
          <span>{formatUsd(data.target_usd)}</span>
        </div>
        <div className="h-3 rounded-full bg-sol-base02 overflow-hidden">
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${clampedPct}%`,
              background: reached ? SOL.green : SOL.cyan,
            }}
          />
        </div>
      </div>

      {/* 4 metric cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 px-1">
        <FireMetricCard
          title="Net Worth"
          value={formatUsd(data.net_worth_usd)}
          sub={`${formatAmount(data.net_worth_usd)} USD`}
          valueColor="text-sol-blue"
        />
        <FireMetricCard
          title="FIRE Target"
          value={formatUsd(data.target_usd)}
          sub={`${formatUsd(data.monthly_expense_usd)}/mo × 12 ÷ ${(data.withdrawal_rate * 100).toFixed(1)}%`}
          valueColor="text-sol-yellow"
        />
        <FireMetricCard
          title="Gap"
          value={formatUsd(data.gap_usd)}
          sub={
            data.projected_date
              ? `Projected: ${data.projected_date}` + (data.projected_months_to_target != null ? ` (${data.projected_months_to_target.toFixed(1)} mo)` : "")
              : "Need positive savings"
          }
          valueColor={reached ? "text-sol-green" : "text-sol-red"}
        />
        <FireMetricCard
          title="YTD Savings Rate"
          value={data.ytd_savings_rate != null ? `${(data.ytd_savings_rate * 100).toFixed(1)}%` : "—"}
          sub={`${formatUsd(ytdNet)} saved · avg ${formatUsd(avgMonthlySavings)}/mo`}
          valueColor={data.ytd_savings_rate != null && data.ytd_savings_rate >= 0 ? "text-sol-green" : "text-sol-red"}
        />
      </div>
    </div>
  );
}

type ISChartTab = "net-profit" | "income" | "expenses";

function NetProfitTooltip({ active, payload, label }: {
  active?: boolean;
  payload?: any[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const dataPoint = payload[0]?.payload;
  if (!dataPoint) return null;
  const netProfit = dataPoint["Net Profit"] as number;
  const income = Math.abs(dataPoint["Income"] as number);
  const expenses = dataPoint["Expenses"] as number;
  return (
    <div className="rounded px-2 py-1.5 text-xs" style={{ background: SOL.base02, border: `1px solid ${SOL.base01}` }}>
      <div style={{ color: SOL.base1 }} className="mb-1">{tooltipLabel(payload, label)}</div>
      <div className="flex items-center gap-2">
        <span className="inline-block w-2 h-2 rounded-full" style={{ background: netProfit >= 0 ? SOL.green : SOL.red }} />
        <span style={{ color: SOL.base1, fontWeight: 500 }}>Net Profit: {formatAmount(netProfit)} USD</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="inline-block w-2 h-2 rounded-full" style={{ background: SOL.green }} />
        <span style={{ color: SOL.base0 }}>Income: {formatAmount(income)} USD</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="inline-block w-2 h-2 rounded-full" style={{ background: SOL.red }} />
        <span style={{ color: SOL.base0 }}>Expenses: {formatAmount(expenses)} USD</span>
      </div>
    </div>
  );
}

function IncomeStatementChart({ data, granularity, onGranularityChange }: { data: IncomeStatementHistoryItem[]; granularity: Granularity; onGranularityChange: (v: Granularity) => void }) {
  const [chartTab, setChartTab] = useState<ISChartTab>(() => (localStorage.getItem("finance-is-chart-tab") as ISChartTab) || "net-profit");

  const chartData = useMemo(() =>
    data.map((item) => {
      const income = Math.abs(item.income.USD || 0);
      const expenses = item.expenses.USD || 0;
      return {
        period: formatPeriodLabel(item.period),
        rawPeriod: item.period,
        Income: -income,       // downward
        Expenses: expenses,    // upward
        "Net Profit": income - expenses,
      };
    }),
    [data]
  );

  return (
    <div className="relative">
      <div className="absolute top-0 right-2 z-10">
        <GranularityToggle value={granularity} onChange={onGranularityChange} />
      </div>
      <ResponsiveContainer width="100%" height={300}>
        {chartTab === "net-profit" ? (
          <BarChart data={chartData} stackOffset="sign" margin={{ top: 10, right: 20, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={SOL.base02} />
            <XAxis dataKey="period" tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} />
            <YAxis tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} tickFormatter={(v) => `${(Math.abs(v) / 1000).toFixed(0)}k`} />
            <Tooltip content={<NetProfitTooltip />} cursor={{ fill: "rgba(147, 161, 161, 0.15)" }} />
            <Bar dataKey="Income" stackId="income-statement" fill={SOL.green} isAnimationActive={false} />
            <Bar dataKey="Expenses" stackId="income-statement" fill={SOL.red} isAnimationActive={false} />
          </BarChart>
        ) : chartTab === "income" ? (
          <BarChart data={chartData} margin={{ top: 10, right: 20, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={SOL.base02} />
            <XAxis dataKey="period" tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} />
            <YAxis tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} tickFormatter={(v) => `${(Math.abs(v) / 1000).toFixed(0)}k`} />
            <Tooltip content={<ChartTooltipContent formatter={(v) => formatAmount(Math.abs(v)) + " USD"} />} cursor={{ fill: "rgba(147, 161, 161, 0.15)" }} />
            <Bar dataKey="Income" fill={SOL.green} isAnimationActive={false} />
          </BarChart>
        ) : (
          <BarChart data={chartData} margin={{ top: 10, right: 20, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={SOL.base02} />
            <XAxis dataKey="period" tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} />
            <YAxis tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
            <Tooltip content={<ChartTooltipContent formatter={(v) => formatAmount(v) + " USD"} />} cursor={{ fill: "rgba(147, 161, 161, 0.15)" }} />
            <Bar dataKey="Expenses" fill={SOL.red} isAnimationActive={false} />
          </BarChart>
        )}
      </ResponsiveContainer>
      <div className="flex justify-center gap-1 mt-1">
        {([["net-profit", "Net Profit"], ["income", "Income"], ["expenses", "Expenses"]] as const).map(([t, label]) => (
          <button
            key={t}
            onClick={() => { setChartTab(t); localStorage.setItem("finance-is-chart-tab", t); }}
            className={`px-2 py-0.5 rounded text-xs cursor-pointer ${
              chartTab === t
                ? "bg-sol-blue text-sol-base03"
                : "bg-sol-base02 text-sol-base0 hover:text-sol-base1"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

// --- Main Component ---

interface FinanceViewerProps {
  vmName?: string | null;
}

export default function FinanceViewer({ vmName }: FinanceViewerProps) {
  const [tab, setTab] = useState<Tab>(() => (localStorage.getItem("finance-tab") as Tab) || "balance-sheet");
  const [timeInput, setTimeInput] = useState(() => localStorage.getItem("finance-time") || "year");
  const [committedTime, setCommittedTime] = useState(() => localStorage.getItem("finance-time") || "year");
  const [granularity, setGranularity] = useState<Granularity>(() => (localStorage.getItem("finance-granularity") as Granularity) || "monthly");
  const [holdingsGranularity, setHoldingsGranularity] = useState<HoldingsGranularity>(() => (localStorage.getItem("finance-holdings-granularity") as HoldingsGranularity) || "monthly");
  const [holdingsOverTime, setHoldingsOverTime] = useState<boolean>(() => localStorage.getItem("finance-holdings-over-time") === "1");
  const [holdingsRiskyOnly, setHoldingsRiskyOnly] = useState<boolean>(() => localStorage.getItem("holdings-risky-only") === "1");
  const vmQuery = vmName ? `&vm_name=${encodeURIComponent(vmName)}` : "";
  const vmQueryOnly = vmName ? `?vm_name=${encodeURIComponent(vmName)}` : "";

  const handleGranularityChange = (v: Granularity) => {
    setGranularity(v);
    localStorage.setItem("finance-granularity", v);
  };

  const handleHoldingsRiskyOnlyChange = (v: boolean) => {
    setHoldingsRiskyOnly(v);
    localStorage.setItem("holdings-risky-only", v ? "1" : "0");
  };

  const handleHoldingsOverTimeChange = (v: boolean) => {
    setHoldingsOverTime(v);
    localStorage.setItem("finance-holdings-over-time", v ? "1" : "0");
  };

  const handleHoldingsGranularityChange = (v: HoldingsGranularity) => {
    setHoldingsGranularity(v);
    localStorage.setItem("finance-holdings-granularity", v);
  };

  // Table data fetches (always fetch for active tab)
  const bsKey = tab === "balance-sheet"
    ? `${API}/api/finance/balance-sheet?time=${encodeURIComponent(committedTime)}&convert=USD${vmQuery}`
    : null;

  const isKey = tab === "income-statement"
    ? `${API}/api/finance/income-statement?time=${encodeURIComponent(committedTime)}${vmQuery}`
    : null;

  const holdingsKey = tab === "holdings" && !holdingsOverTime
    ? `${API}/api/finance/positions${vmQueryOnly}${vmQueryOnly ? "&" : "?"}risky_only=${holdingsRiskyOnly ? "true" : "false"}`
    : null;
  const holdingsAllKey = tab === "holdings" && !holdingsOverTime && holdingsRiskyOnly
    ? `${API}/api/finance/positions${vmQueryOnly}${vmQueryOnly ? "&" : "?"}risky_only=false`
    : null;
  const holdingsRiskyKey = tab === "holdings" && !holdingsOverTime && !holdingsRiskyOnly
    ? `${API}/api/finance/positions${vmQueryOnly}${vmQueryOnly ? "&" : "?"}risky_only=true`
    : null;

  const transactionsKey = tab === "transactions"
    ? `${API}/api/finance/transactions${vmQueryOnly}`
    : null;

  const fireKey = tab === "fire"
    ? `${API}/api/finance/fire-progress${vmQueryOnly}`
    : null;

  // Chart data fetches (also always fetch for active tab, except holdings)
  const bsHistKey = tab === "balance-sheet" || tab === "fire"
    ? `${API}/api/finance/balance-sheet?history=true&granularity=${granularity}&convert=USD&time=${encodeURIComponent(committedTime)}${vmQuery}`
    : null;

  const isHistKey = tab === "income-statement"
    ? `${API}/api/finance/income-statement?history=true&granularity=${granularity}&convert=USD&time=${encodeURIComponent(committedTime)}${vmQuery}`
    : null;

  const bs = useFinanceEnvelope<BalanceSheetData>(bsKey);
  const is = useFinanceEnvelope<IncomeStatementData>(isKey);
  const holdings = useFinanceEnvelope<HoldingPosition[]>(holdingsKey);
  const holdingsAll = useFinanceEnvelope<HoldingPosition[]>(holdingsAllKey);
  const holdingsRisky = useFinanceEnvelope<HoldingPosition[]>(holdingsRiskyKey);
  const transactions = useFinanceEnvelope<TransactionRow[]>(transactionsKey);
  const fire = useFinanceEnvelope<FireProgressData>(fireKey);
  const bsHist = useFinanceEnvelope<BalanceSheetHistoryItem[]>(bsHistKey);
  const isHist = useFinanceEnvelope<IncomeStatementHistoryItem[]>(isHistKey);

  const bsData = bs.data?.data;
  const isData = is.data?.data;
  const holdingsData = holdings.data?.data;
  const holdingsAllData = holdingsRiskyOnly ? holdingsAll.data?.data : holdingsData;
  const holdingsRiskyData = holdingsRiskyOnly ? holdingsData : holdingsRisky.data?.data;
  const transactionsData = transactions.data?.data;
  const fireData = fire.data?.data;
  const bsHistData = bsHist.data?.data;
  const isHistData = isHist.data?.data;
  const holdingRows = useMemo(() => holdingsData ? toHoldingRows(holdingsData) : [], [holdingsData]);

  const activeEnvelope = tab === "transactions" ? transactions.data : tab === "holdings" ? holdings.data : tab === "balance-sheet" ? bs.data : tab === "income-statement" ? is.data : fire.data;

  const mutateActive = async () => {
    await Promise.all([bs.mutate(), is.mutate(), holdings.mutate(), transactions.mutate(), fire.mutate(), bsHist.mutate(), isHist.mutate()]);
  };

  const refreshSnapshots = async () => {
    const res = await authFetch(`${API}/api/finance/refresh${vmQueryOnly}`, { method: "POST" });
    if (!res.ok) throw new Error("Failed to refresh finance data");
    await mutateActive();
  };

  // Combined loading/error: table OR chart loading
  const tableLoading = tab === "balance-sheet" ? bs.isLoading : tab === "income-statement" ? is.isLoading : tab === "fire" ? fire.isLoading : tab === "transactions" ? transactions.isLoading : holdings.isLoading;
  const chartLoading = tab === "balance-sheet" || tab === "fire" ? bsHist.isLoading : tab === "income-statement" ? isHist.isLoading : false;
  const loading = tableLoading && chartLoading;

  const tableError = tab === "balance-sheet" ? bs.error : tab === "income-statement" ? is.error : tab === "fire" ? fire.error : tab === "transactions" ? transactions.error : holdings.error;
  const chartError = tab === "balance-sheet" || tab === "fire" ? bsHist.error : tab === "income-statement" ? isHist.error : null;
  const error = tableError && chartError;

  return (
    <div className="h-full overflow-y-auto bg-sol-base03 text-sm">
      {/* Top bar */}
      <div className="sticky top-0 z-20 bg-sol-base03 border-b border-sol-base02 px-3 py-2 space-y-2">
        <div className="flex items-center justify-end gap-2">
          <span className="inline-flex items-center gap-1 rounded bg-sol-base02 px-2 py-1 text-[10px] text-sol-base0">
            <>Synced {formatRelativeTime(activeEnvelope?.synced_at)}</>
          </span>
          <button
            onClick={() => void refreshSnapshots()}
            className="px-2 py-1 rounded text-xs cursor-pointer bg-sol-base02 text-sol-base0 hover:text-sol-base1"
            title="Refresh cached finance tables"
          >
            ↻
          </button>
          <input
            type="text"
            value={timeInput}
            onChange={(e) => setTimeInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { const v = timeInput.trim(); setCommittedTime(v); localStorage.setItem("finance-time", v); } }}
            onBlur={() => { const v = timeInput.trim(); setCommittedTime(v); localStorage.setItem("finance-time", v); }}
            placeholder="month, 2024, 2024-q2, day-1 - day"
            className="px-2 py-1 rounded text-xs w-56 bg-sol-base02 text-sol-base1 border border-sol-base01 outline-none placeholder:text-sol-base01"
          />
        </div>
        <div className="flex justify-center gap-1">
          {([["balance-sheet", "Balance Sheet"], ["income-statement", "Income Statement"], ["holdings", "Holdings"], ["transactions", "Transactions"], ["fire", "FIRE"]] as const).map(([t, label]) => (
            <button
              key={t}
              onClick={() => { setTab(t); localStorage.setItem("finance-tab", t); }}
              className={`px-2 py-1 rounded text-xs cursor-pointer ${
                tab === t
                  ? "bg-sol-blue text-sol-base03"
                  : "bg-sol-base02 text-sol-base0 hover:text-sol-base1"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="px-1 py-2">
        {loading ? (
          <p className="text-sol-base01 italic px-3">Loading...</p>
        ) : error ? (
          <p className="text-sol-red px-3">Error loading data</p>
        ) : tab === "balance-sheet" ? (
          <>
            {bsHist.isLoading ? (
              <p className="text-sol-base01 italic px-3 mb-2">Loading chart...</p>
            ) : bsHist.error ? null : bsHistData ? (
              <div className="mb-3"><BalanceSheetChart data={bsHistData} granularity={granularity} onGranularityChange={handleGranularityChange} /></div>
            ) : null}
            {bs.isLoading ? (
              <p className="text-sol-base01 italic px-3">Loading...</p>
            ) : bsData ? (
              <div className="flex gap-2">
                <div className="flex-1 min-w-0">
                  <AccountTree root={bsData.assets} title="Assets" />
                </div>
                <div className="flex-1 min-w-0">
                  <AccountTree root={bsData.liabilities} title="Liabilities" />
                  <EquitySummary assets={bsData.assets} liabilities={bsData.liabilities} />
                </div>
              </div>
            ) : null}
          </>
        ) : tab === "income-statement" ? (
          <>
            {isHist.isLoading ? (
              <p className="text-sol-base01 italic px-3 mb-2">Loading chart...</p>
            ) : isHist.error ? null : isHistData ? (
              <div className="mb-3"><IncomeStatementChart data={isHistData} granularity={granularity} onGranularityChange={handleGranularityChange} /></div>
            ) : null}
            {is.isLoading ? (
              <p className="text-sol-base01 italic px-3">Loading...</p>
            ) : isData ? (
              <div className="flex gap-2">
                <div className="flex-1 min-w-0">
                  <AccountTree root={isData.income} title="Income" />
                </div>
                <div className="flex-1 min-w-0">
                  <AccountTree root={isData.expenses} title="Expenses" />
                </div>
              </div>
            ) : null}
          </>
        ) : tab === "holdings" ? (
          <>
            {holdingsOverTime ? (
              <AssetsOverTimeView vmName={vmName} riskyOnly={holdingsRiskyOnly} time={committedTime} granularity={holdingsGranularity} onGranularityChange={handleHoldingsGranularityChange} controls={<HoldingsModeToggle riskyOnly={holdingsRiskyOnly} overTime={holdingsOverTime} onRiskyOnlyChange={handleHoldingsRiskyOnlyChange} onOverTimeChange={handleHoldingsOverTimeChange} />} />
            ) : (
              holdings.isLoading ? (
                <p className="text-sol-base01 italic px-3">Loading...</p>
              ) : holdingsData ? (
                <>
                  <HoldingsPieChart positions={holdingsData} />
                  <div className="flex items-center justify-between gap-3 px-2 py-3">
                    <RiskyAllocationSummary allPositions={holdingsAllData} riskyPositions={holdingsRiskyData} loading={holdings.isLoading || holdingsAll.isLoading || holdingsRisky.isLoading} />
                    <HoldingsModeToggle riskyOnly={holdingsRiskyOnly} overTime={holdingsOverTime} onRiskyOnlyChange={handleHoldingsRiskyOnlyChange} onOverTimeChange={handleHoldingsOverTimeChange} />
                  </div>
                  <HoldingsTable holdings={holdingRows} totals={holdingTotals(holdingRows)} syncedAt={holdings.data?.synced_at} riskyOnly={holdingsRiskyOnly} onRiskyOnlyChange={handleHoldingsRiskyOnlyChange} vmName={vmName} />
                </>
              ) : null
            )}
          </>
        ) : tab === "transactions" ? (
          transactions.isLoading ? (
            <p className="text-sol-base01 italic px-3">Loading...</p>
          ) : transactionsData ? (
            <TransactionsTable rows={transactionsData} syncedAt={transactions.data?.synced_at} />
          ) : null
        ) : tab === "fire" ? (
          <>
            {fire.isLoading ? (
              <p className="text-sol-base01 italic px-3">Loading...</p>
            ) : fire.error ? (
              <p className="text-sol-red px-3">Error loading FIRE progress</p>
            ) : fireData ? (
              <div className="px-2"><FireProgressView data={fireData} /></div>
            ) : null}
            {bsHist.isLoading ? (
              <p className="text-sol-base01 italic px-3 mt-3">Loading chart...</p>
            ) : bsHist.error ? null : bsHistData ? (
              <div className="mt-4">
                <BalanceSheetChart
                  data={bsHistData}
                  granularity={granularity}
                  onGranularityChange={handleGranularityChange}
                  targetLine={fireData?.target_usd}
                />
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}
