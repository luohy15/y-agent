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
  assets?: Record<string, number>;
  liabilities?: Record<string, number>;
  total?: Record<string, number>;
  risky?: Record<string, number>;
}

interface IncomeStatementHistoryItem {
  period: string;
  income: Record<string, number>;
  expenses: Record<string, number>;
}

interface IncomeStatementCategoriesHistoryItem {
  period: string;
  categories: Record<string, Record<string, number>>;
  income_categories?: Record<string, Record<string, number>>;
  expense_categories?: Record<string, Record<string, number>>;
  total: Record<string, number>;
  income_total?: Record<string, number>;
  expense_total?: Record<string, number>;
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

interface RiskyAllocationSummaryData {
  total_base: number;
  risky_base: number;
  risky_pct: number | null;
  base_currency: string;
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
  summary?: RiskyAllocationSummaryData;
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

function accountSortMagnitude(node: AccountNode): number {
  const totals = totalBalance(node);
  if (totals.USD != null) return Math.abs(totals.USD);
  return Object.values(totals).reduce((sum, amt) => sum + Math.abs(amt), 0);
}

function sortedChildrenByValue(node: AccountNode): AccountNode[] {
  return [...node.children].sort((a, b) => accountSortMagnitude(b) - accountSortMagnitude(a));
}

function mapAccountBalances(node: AccountNode, mapper: (amount: number) => number): AccountNode {
  return {
    account: node.account,
    balance: Object.fromEntries(Object.entries(node.balance).map(([currency, amount]) => [currency, mapper(amount)])),
    children: node.children.map((child) => mapAccountBalances(child, mapper)),
  };
}

function balanceUsdValue(balance: Record<string, number> | undefined): number {
  return balance?.USD || 0;
}

function incomeUsdValue(balance: Record<string, number> | undefined): number {
  return Math.abs(balanceUsdValue(balance));
}

function positiveUsdValue(balance: Record<string, number> | undefined): number {
  return Math.max(0, balanceUsdValue(balance));
}

function accountPieRows(root: AccountNode, valueForBalance: (balance: Record<string, number>) => number) {
  const rows = root.children
    .map((child) => ({ name: child.account, label: shortName(child.account), value: valueForBalance(totalBalance(child)) }))
    .filter((row) => row.value > 0.005)
    .sort((a, b) => b.value - a.value);
  const total = rows.reduce((sum, row) => sum + row.value, 0);
  return total > 0 ? rows.map((row) => ({ ...row, allocation: row.value / total })) : [];
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
  const sortedChildren = useMemo(() => sortedChildrenByValue(node), [node]);

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
      {expanded && sortedChildren.map((child) => (
        <AccountRow key={child.account} node={child} depth={depth + 1} />
      ))}
    </>
  );
}

function AccountTree({ root, title }: { root: AccountNode; title: string }) {
  const totals = useMemo(() => totalBalance(root), [root]);
  const sortedChildren = useMemo(() => sortedChildrenByValue(root), [root]);
  return (
    <div className="mb-4">
      <div className="flex items-center justify-between px-3 py-1.5 bg-sol-base02/50 border-b border-sol-base02">
        <span className="text-sol-base1 font-medium text-xs uppercase tracking-wide">{title}</span>
        <BalanceDisplay balance={totals} />
      </div>
      <table className="w-full text-sm">
        <tbody>
          {sortedChildren.map((child) => (
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

function NetIncomeSummary({ income, expenses }: { income: AccountNode; expenses: AccountNode }) {
  const net = useMemo(
    () => incomeUsdValue(totalBalance(income)) - balanceUsdValue(totalBalance(expenses)),
    [income, expenses],
  );

  return (
    <div className="mb-4">
      <div className="flex items-center justify-between px-3 py-1.5 bg-sol-base02/50 border-b border-sol-base02">
        <span className="text-sol-base1 font-medium text-xs uppercase tracking-wide">Net Income (Income − Expenses)</span>
        <BalanceDisplay balance={{ USD: net }} />
      </div>
    </div>
  );
}

function isValidAmount(v: unknown): v is HoldingAmount {
  return v != null && typeof v === "object" && !Array.isArray(v) && "number" in v;
}

type HoldingSortKey = "asset" | "units" | "avg_cost" | "price" | "book_value" | "market_value" | "allocation" | "pnl_amount" | "pnl";
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
    case "pnl_amount": return getNumericVal(h.market_value) - getNumericVal(h.book_value);
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

function RiskyAllocationSummary({ summary, loading }: { summary?: RiskyAllocationSummaryData; loading: boolean }) {

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
          ) : summary && summary.risky_pct != null ? (
            <>
              <div className="text-sol-blue text-lg font-semibold">{(summary.risky_pct * 100).toFixed(1)}%</div>
              <div className="text-sol-base01 text-[10px]">{formatAmount(summary.risky_base)} / {formatAmount(summary.total_base)} {summary.base_currency}</div>
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
            <SortableHeader label="P&L" sortKey="pnl_amount" align="right" {...hp} />
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
                  {(() => {
                    const pnlAmount = isValidAmount(h.market_value) && isValidAmount(h.book_value) && h.market_value.currency === h.book_value.currency
                      ? h.market_value.number - h.book_value.number
                      : null;
                    const pnlPct = h.unrealized_profit_pct;
                    const colorClass = (pnlPct ?? 0) > 0 ? "text-sol-green" : (pnlPct ?? 0) < 0 ? "text-sol-red" : "text-sol-base0";
                    return (
                      <>
                        <td className={`py-0.5 px-3 text-right tabular-nums ${colorClass}`}>
                          {pnlAmount != null ? <>{pnlAmount > 0 ? "+" : ""}{formatAmount(pnlAmount)} <span className="text-sol-base01 text-xs">{h.market_value.currency}</span></> : "—"}
                        </td>
                        <td className={`py-0.5 px-3 text-right tabular-nums ${colorClass}`}>
                          {pnlPct != null ? <>{pnlPct > 0 ? "+" : ""}{formatAmount(pnlPct)}%</> : "—"}
                        </td>
                      </>
                    );
                  })()}
                </tr>
                {isExpanded ? (
                  <tr className="border-y border-sol-base02 bg-sol-base03">
                    <td colSpan={9} className="px-3 py-3">
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
                  {bv && mv && bv.currency === mv.currency ? <>{mv.number - bv.number > 0 ? "+" : ""}{formatAmount(mv.number - bv.number)} <span className="text-sol-base01 text-xs">{mv.currency}</span></> : "—"}
                </td>
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

type ModeTab = "balance-sheet" | "income-statement" | "holdings";
type ViewMode = "live" | "over-time";
type SharedGranularity = "weekly" | "monthly" | "yearly";
type ISChartTab = "net-profit" | "income" | "expenses";
const ACCOUNT_COLORS = [SOL.blue, SOL.cyan, SOL.green, SOL.orange, SOL.magenta, SOL.violet, SOL.yellow, SOL.red];

function isModeTab(tab: Tab): tab is ModeTab {
  return tab === "balance-sheet" || tab === "income-statement" || tab === "holdings";
}

function normalizeMode(value: string | null): ViewMode | null {
  return value === "live" || value === "over-time" ? value : null;
}

function normalizeGranularity(value: string | null): SharedGranularity | null {
  return value === "weekly" || value === "monthly" || value === "yearly" ? value : null;
}

function initialMode(): ViewMode {
  const stored = normalizeMode(localStorage.getItem("finance-mode"));
  if (stored) return stored;

  const byTab = localStorage.getItem("finance-mode-by-tab");
  if (byTab) {
    try {
      const parsed = JSON.parse(byTab) as Partial<Record<ModeTab, string>>;
      return normalizeMode(parsed["balance-sheet"] ?? null)
        ?? normalizeMode(parsed["income-statement"] ?? null)
        ?? normalizeMode(parsed.holdings ?? null)
        ?? "live";
    } catch {
      // Fall through to older legacy keys.
    }
  }

  return localStorage.getItem("finance-expenses-over-time") === "1" || localStorage.getItem("finance-holdings-over-time") === "1" ? "over-time" : "live";
}

function initialGranularity(): SharedGranularity {
  const stored = normalizeGranularity(localStorage.getItem("finance-granularity"));
  if (stored) return stored;

  const storedByTab = localStorage.getItem("finance-granularity-by-tab");
  if (storedByTab) {
    try {
      const parsed = JSON.parse(storedByTab) as Partial<Record<ModeTab, string>>;
      return normalizeGranularity(parsed["balance-sheet"] ?? null)
        ?? normalizeGranularity(parsed["income-statement"] ?? null)
        ?? normalizeGranularity(parsed.holdings ?? null)
        ?? "monthly";
    } catch {
      // Fall through to legacy migration.
    }
  }

  return normalizeGranularity(localStorage.getItem("finance-expenses-granularity"))
    ?? normalizeGranularity(localStorage.getItem("finance-holdings-granularity"))
    ?? "monthly";
}

function ModeToggle({ value, onChange }: { value: ViewMode; onChange: (v: ViewMode) => void }) {
  return (
    <div className="flex gap-1">
      {([["live", "Live"], ["over-time", "Over time"]] as const).map(([mode, label]) => (
        <button
          key={mode}
          onClick={() => onChange(mode)}
          className={`px-2 py-1 rounded text-xs cursor-pointer ${
            value === mode
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

function SharedGranularityToggle({ value, onChange }: { value: SharedGranularity; onChange: (v: SharedGranularity) => void }) {
  return (
    <div className="flex gap-1">
      {(["weekly", "monthly", "yearly"] as const).map((g) => (
        <button
          key={g}
          onClick={() => onChange(g)}
          className={`px-1.5 py-1 rounded text-[10px] cursor-pointer ${
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

function AccountPieTooltip({ active, payload }: {
  active?: boolean;
  payload?: Array<{ payload?: { name: string; label: string; value: number; allocation: number }; color?: string }>;
}) {
  if (!active || !payload?.length) return null;
  const item = payload[0]?.payload;
  if (!item) return null;
  return (
    <div className="rounded px-2 py-1.5 text-xs" style={{ background: SOL.base02, border: `1px solid ${SOL.base01}` }}>
      <div style={{ color: SOL.base1 }} className="mb-1">{shortName(item.name)}</div>
      <div className="flex items-center gap-2">
        <span className="inline-block w-2 h-2 rounded-full" style={{ background: payload[0]?.color ?? SOL.base0 }} />
        <span style={{ color: SOL.base0 }}>{formatAmount(item.value)} USD · {(item.allocation * 100).toFixed(1)}%</span>
      </div>
    </div>
  );
}

function AccountPieChart({ title, subtitle, data, emptyLabel = "No data yet" }: {
  title: string;
  subtitle: string;
  data: Array<{ name: string; label: string; value: number; allocation: number }>;
  emptyLabel?: string;
}) {
  return (
    <div className="rounded border border-sol-base02 bg-sol-base03 p-3">
      <div className="mb-2">
        <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">{title}</div>
        <div className="text-sol-base01 text-[10px]">{subtitle}</div>
      </div>
      {data.length === 0 ? (
        <div className="flex h-56 items-center justify-center text-sol-base01">{emptyLabel}</div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <PieChart margin={{ top: 10, right: 20, left: 20, bottom: 5 }}>
            <Pie data={data} dataKey="value" nameKey="label" cx="50%" cy="50%" outerRadius={95} label={(props) => {
              const payload = props.payload as { label?: string; allocation?: number } | undefined;
              return (payload?.allocation ?? 0) >= 0.03 ? (payload?.label ?? "") : "";
            }} labelLine={false} isAnimationActive={false}>
              {data.map((entry, index) => (
                <Cell key={entry.name} fill={HOLDINGS_PIE_COLORS[index % HOLDINGS_PIE_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip content={<AccountPieTooltip />} />
          </PieChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

function BalanceSheetLivePieCharts({ assets, liabilities }: { assets: AccountNode; liabilities: AccountNode }) {
  const assetData = useMemo(() => accountPieRows(assets, positiveUsdValue), [assets]);
  const liabilityData = useMemo(() => accountPieRows(liabilities, incomeUsdValue), [liabilities]);
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <AccountPieChart title="Assets by account" subtitle="Current top-level asset accounts in USD" data={assetData} emptyLabel="No assets yet" />
      <AccountPieChart title="Liabilities by account" subtitle="Current top-level liability accounts in USD" data={liabilityData} emptyLabel="No liabilities yet" />
    </div>
  );
}

function IncomeStatementLivePieCharts({ income, expenses }: { income: AccountNode; expenses: AccountNode }) {
  const incomeData = useMemo(() => accountPieRows(income, incomeUsdValue), [income]);
  const expenseData = useMemo(() => accountPieRows(expenses, positiveUsdValue), [expenses]);
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <AccountPieChart title="Income by category" subtitle="Selected period income accounts in USD" data={incomeData} emptyLabel="No income yet" />
      <AccountPieChart title="Expenses by category" subtitle="Selected period expense accounts in USD" data={expenseData} emptyLabel="No expenses yet" />
    </div>
  );
}

function IncomeStatementOverTimeTable({ data, chartTab, categoryData }: { data?: IncomeStatementHistoryItem[]; chartTab: ISChartTab; categoryData?: IncomeStatementCategoriesHistoryItem[] }) {
  if (chartTab === "income") {
    if (!categoryData) return null;
    return <IncomeStatementCategoriesTableView data={categoryData} kind="income" />;
  }
  if (chartTab === "expenses") {
    if (!categoryData) return null;
    return <IncomeStatementCategoriesTableView data={categoryData} kind="expenses" />;
  }
  return data ? <IncomeStatementHistoryTable data={data} chartTab={chartTab} /> : null;
}

function IncomeStatementOverTimeView({ data, categoryData, categoryState, chartTab, onChartTabChange }: {
  data?: IncomeStatementHistoryItem[];
  categoryData?: IncomeStatementCategoriesHistoryItem[];
  categoryState: { isLoading: boolean; error?: unknown };
  chartTab: ISChartTab;
  onChartTabChange: (v: ISChartTab) => void;
}) {
  const chart = (() => {
    if (chartTab === "income" || chartTab === "expenses") {
      const label = chartTab === "income" ? "income" : "expenses";
      if (categoryState.isLoading) return <p className="text-sol-base01 italic px-3 mb-2">Loading {label}...</p>;
      if (categoryState.error && !isAbortError(categoryState.error)) return null;
      if (categoryData) return <IncomeStatementChart data={data || []} categoryData={categoryData} chartTab={chartTab} onChartTabChange={onChartTabChange} />;
    }
    if (!data) return null;
    return <IncomeStatementChart data={data} categoryData={categoryData} chartTab={chartTab} onChartTabChange={onChartTabChange} />;
  })();

  return (
    <div className="space-y-3">
      {chart}
      {(chartTab === "income" || chartTab === "expenses") && categoryState.isLoading ? (
        <p className="text-sol-base01 italic px-3">Loading {chartTab}...</p>
      ) : (chartTab === "income" || chartTab === "expenses") && categoryState.error && !isAbortError(categoryState.error) ? (
        <p className="text-sol-red px-3">Error loading {chartTab}</p>
      ) : (
        <IncomeStatementOverTimeTable data={data} chartTab={chartTab} categoryData={categoryData} />
      )}
    </div>
  );
}

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

function BalanceSheetChart({ data, targetLine }: { data: BalanceSheetHistoryItem[]; targetLine?: number }) {
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

function categoryBalances(item: IncomeStatementCategoriesHistoryItem, kind: "income" | "expenses") {
  return kind === "income" ? (item.income_categories || {}) : (item.expense_categories || item.categories);
}

function categoryBalanceValue(balance: Record<string, number> | undefined, kind: "income" | "expenses"): number {
  return kind === "income" ? incomeUsdValue(balance) : balanceUsdValue(balance);
}

function totalCategoryValue(categories: Record<string, Record<string, number>>, kind: "income" | "expenses"): number {
  return Object.values(categories).reduce((sum, balance) => sum + categoryBalanceValue(balance, kind), 0);
}

function categoryPeriodTotal(item: IncomeStatementCategoriesHistoryItem, kind: "income" | "expenses"): number {
  const total = kind === "income" ? item.income_total : (item.expense_total || item.total);
  const explicitTotal = categoryBalanceValue(total, kind);
  return explicitTotal || totalCategoryValue(categoryBalances(item, kind), kind);
}

function buildIncomeStatementCategorySeries(data: IncomeStatementCategoriesHistoryItem[], kind: "income" | "expenses") {
  const latest = data[data.length - 1];
  const totals = new Map<string, number>();
  for (const item of data) {
    for (const [category, balance] of Object.entries(categoryBalances(item, kind))) {
      totals.set(category, Math.max(totals.get(category) || 0, Math.abs(categoryBalanceValue(balance, kind))));
    }
  }
  const ordered = Array.from(totals.entries())
    .filter(([, value]) => value > 0.005)
    .sort((a, b) => categoryBalanceValue(latest ? categoryBalances(latest, kind)[b[0]] : undefined, kind) - categoryBalanceValue(latest ? categoryBalances(latest, kind)[a[0]] : undefined, kind));
  const topCategories = ordered.slice(0, 7).map(([category]) => category);
  const otherCategories = ordered.slice(7).map(([category]) => category);
  return otherCategories.length ? [...topCategories, "Other"] : topCategories;
}

function incomeStatementCategoryRows(item: IncomeStatementCategoriesHistoryItem | undefined, categories: string[], kind: "income" | "expenses") {
  if (!item) return [];
  const balances = categoryBalances(item, kind);
  return categories
    .map((category) => ({
      category,
      value: category === "Other"
        ? Object.entries(balances).reduce((sum, [name, balance]) => sum + (categories.includes(name) ? 0 : categoryBalanceValue(balance, kind)), 0)
        : categoryBalanceValue(balances[category], kind),
    }))
    .filter((row) => Math.abs(row.value) > 0.005)
    .sort((a, b) => b.value - a.value);
}

function incomeStatementCategoryChartRows(data: IncomeStatementCategoriesHistoryItem[], categories: string[], kind: "income" | "expenses") {
  return data.map((item) => {
    const balances = categoryBalances(item, kind);
    const row: Record<string, string | number> = {
      period: formatPeriodLabel(item.period),
      rawPeriod: item.period,
      Total: categoryPeriodTotal(item, kind),
    };
    for (const category of categories) {
      if (category === "Other") continue;
      row[category] = categoryBalanceValue(balances[category], kind);
    }
    if (categories.includes("Other")) {
      const named = new Set(categories.filter((category) => category !== "Other"));
      row.Other = Object.entries(balances).reduce((sum, [category, balance]) => sum + (named.has(category) ? 0 : categoryBalanceValue(balance, kind)), 0);
    }
    return row;
  });
}

function incomeStatementCategoryPeriodTotals(data: IncomeStatementCategoriesHistoryItem[], kind: "income" | "expenses") {
  return Object.fromEntries(data.map((item) => [item.period, categoryPeriodTotal(item, kind)]));
}

function incomeStatementCategoryPeriodTableRows(data: IncomeStatementCategoriesHistoryItem[], categories: string[], kind: "income" | "expenses", sortColumn: string, sortDir: "asc" | "desc") {
  return categories
    .map((category) => ({
      category,
      values: Object.fromEntries(data.map((item) => [item.period, category === "Other"
        ? Object.entries(categoryBalances(item, kind)).reduce((sum, [name, balance]) => sum + (categories.includes(name) ? 0 : categoryBalanceValue(balance, kind)), 0)
        : categoryBalanceValue(categoryBalances(item, kind)[category], kind)
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

function AssetsOverTimeChart({ data, positions }: { data: BalanceSheetPositionsHistoryItem[]; positions: string[] }) {
  const chartData = useMemo(() => positionChartRows(data, positions), [data, positions]);
  const hasData = chartData.some((row) => positions.some((account) => Math.abs(Number(row[account] || 0)) > 0.005));
  const hasRiskyData = data.some((item) => item.risky && totalPositionValue(item.positions) > 0);

  return (
    <div className="relative rounded border border-sol-base02 bg-sol-base03 p-3">
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

function balanceSheetCategoryRows(data: BalanceSheetPositionsHistoryItem[], side: "assets" | "liabilities", sortColumn: string, sortDir: "asc" | "desc") {
  const categories = Array.from(new Set(data.flatMap((item) => Object.keys(item[side] || {}))));
  return categories
    .map((category) => ({
      category,
      values: Object.fromEntries(data.map((item) => [item.period, item[side]?.[category] || 0])),
    }))
    .sort((a, b) => {
      const delta = (a.values[sortColumn] || 0) - (b.values[sortColumn] || 0);
      return sortDir === "asc" ? delta : -delta;
    });
}

function balanceSheetSideTotals(data: BalanceSheetPositionsHistoryItem[], side: "assets" | "liabilities") {
  return Object.fromEntries(data.map((item) => [item.period, Object.values(item[side] || {}).reduce((sum, value) => sum + value, 0)]));
}

function BalanceSheetOverTimeTable({ data }: { data: BalanceSheetPositionsHistoryItem[] }) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const latestPeriod = data[data.length - 1]?.period || "";
  const periodKey = useMemo(() => data.map((item) => item.period).join("|"), [data]);
  const [sortColumn, setSortColumn] = useState(latestPeriod);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const effectiveSortColumn = data.some((item) => item.period === sortColumn) ? sortColumn : latestPeriod;
  const assetRows = useMemo(() => balanceSheetCategoryRows(data, "assets", effectiveSortColumn, sortDir), [data, effectiveSortColumn, sortDir]);
  const liabilityRows = useMemo(() => balanceSheetCategoryRows(data, "liabilities", effectiveSortColumn, sortDir), [data, effectiveSortColumn, sortDir]);
  const assetTotals = useMemo(() => balanceSheetSideTotals(data, "assets"), [data]);
  const liabilityTotals = useMemo(() => balanceSheetSideTotals(data, "liabilities"), [data]);
  const netTotals = useMemo(() => Object.fromEntries(data.map((item) => [item.period, (assetTotals[item.period] || 0) + (liabilityTotals[item.period] || 0)])), [data, assetTotals, liabilityTotals]);

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

  const renderSection = (label: string, rows: { category: string; values: Record<string, number> }[], totals: Record<string, number>, totalLabel: string) => (
    <>
      <tr className="border-t border-sol-base02 bg-sol-base02/30 font-medium">
        <td className="sticky left-0 z-10 bg-sol-base02 py-1 px-3 text-sol-base1 whitespace-nowrap">{label}</td>
        {data.map((item) => (
          <td key={item.period} className="py-1 px-3"></td>
        ))}
      </tr>
      {rows.map((row) => (
        <tr key={`${label}:${row.category}`} className="hover:bg-sol-base02/50">
          <td className="sticky left-0 z-10 bg-sol-base03 py-0.5 px-3 pl-6 text-sol-base0 whitespace-nowrap">{shortName(row.category)}</td>
          {data.map((item) => (
            <td key={item.period} className="py-0.5 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap">{formatAmount(row.values[item.period] || 0)}</td>
          ))}
        </tr>
      ))}
      <tr className="bg-sol-base02/40 font-medium">
        <td className="sticky left-0 z-10 bg-sol-base02 py-1 px-3 text-sol-base1 whitespace-nowrap">{totalLabel}</td>
        {data.map((item) => (
          <td key={item.period} className="py-1 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap">{formatAmount(totals[item.period] || 0)}</td>
        ))}
      </tr>
    </>
  );

  return (
    <div className="rounded border border-sol-base02 bg-sol-base03 overflow-hidden">
      <div className="border-b border-sol-base02 px-3 py-2">
        <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">Balance sheet history</div>
        <div className="text-sol-base01 text-[10px]">Rows are first-level categories under assets and liabilities; columns are periods</div>
      </div>
      {data.length === 0 || (assetRows.length === 0 && liabilityRows.length === 0) ? (
        <div className="px-3 py-8 text-center text-sol-base01">No history yet</div>
      ) : (
        <div ref={scrollRef} className="overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead>
              <tr className="text-sol-base01 border-b border-sol-base02 bg-sol-base02/50">
                <th className="sticky left-0 z-10 bg-sol-base02 text-left font-normal py-1 px-3 whitespace-nowrap">Category</th>
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
              {renderSection("Assets", assetRows, assetTotals, "Total Assets")}
              {renderSection("Liabilities", liabilityRows, liabilityTotals, "Total Liabilities")}
              <tr className="border-t border-sol-base02 bg-sol-base02/60 font-medium">
                <td className="sticky left-0 z-10 bg-sol-base02 py-1 px-3 text-sol-base1 whitespace-nowrap">Net Worth</td>
                {data.map((item) => (
                  <td key={item.period} className="py-1 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap">{formatAmount(netTotals[item.period] || 0)}</td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function HoldingsOverTimeTable({ data, positions }: { data: BalanceSheetPositionsHistoryItem[]; positions: string[] }) {
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
        <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">Holdings history</div>
        <div className="text-sol-base01 text-[10px]">Rows are tickers; columns are periods</div>
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

function AssetsOverTimeView({ vmName, riskyOnly, onRiskyOnlyChange, time, granularity }: { vmName?: string | null; riskyOnly: boolean; onRiskyOnlyChange: (value: boolean) => void; time: string; granularity: SharedGranularity }) {
  const vmQuery = vmName ? `&vm_name=${encodeURIComponent(vmName)}` : "";
  const key = `${API}/api/finance/balance-sheet?history=true&breakdown=positions&granularity=${granularity}&convert=USD&risky_only=${riskyOnly ? "true" : "false"}&time=${encodeURIComponent(time)}${vmQuery}`;
  const history = useFinanceEnvelope<BalanceSheetPositionsHistoryItem[]>(key);
  const data = history.data?.data || [];
  const positions = useMemo(() => buildPositionSeries(data), [data]);
  const showError = !!history.error && !isAbortError(history.error) && !history.data && !history.isLoading && !history.isValidating;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-end px-2">
        <button
          onClick={() => onRiskyOnlyChange(!riskyOnly)}
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
      {history.isLoading ? (
        <p className="text-sol-base01 italic px-3">Loading assets history...</p>
      ) : showError ? (
        <p className="text-sol-red px-3">Error loading assets history</p>
      ) : (
        <>
          <AssetsOverTimeChart data={data} positions={positions} />
          <HoldingsOverTimeTable data={data} positions={positions} />
        </>
      )}
    </div>
  );
}

function ExpensesPieTooltip({ active, payload }: { active?: boolean; payload?: Array<{ name: string; value: number; payload?: { allocation?: number } }> }) {
  if (!active || !payload?.length) return null;
  const item = payload[0];
  return (
    <div className="rounded px-2 py-1.5 text-xs" style={{ background: SOL.base02, border: `1px solid ${SOL.base01}` }}>
      <div style={{ color: SOL.base1 }}>{shortName(item.name)}</div>
      <div style={{ color: SOL.base0 }}>{formatAmount(item.value)} USD</div>
      <div style={{ color: SOL.base0 }}>{(((item.payload?.allocation || 0) * 100)).toFixed(1)}%</div>
    </div>
  );
}

function IncomeStatementCategoriesPieChart({ item, categories, kind }: { item?: IncomeStatementCategoriesHistoryItem; categories: string[]; kind: "income" | "expenses" }) {
  const chartData = useMemo(() => {
    const rows = incomeStatementCategoryRows(item, categories, kind)
      .filter((row) => row.value > 0.005)
      .map((row) => ({ ...row, label: shortName(row.category) }));
    const total = rows.reduce((sum, row) => sum + row.value, 0);
    return total > 0 ? rows.map((row) => ({ ...row, allocation: row.value / total })) : [];
  }, [item, categories, kind]);
  const title = kind === "income" ? "Income by category" : "Expenses by category";
  const emptyLabel = kind === "income" ? "No income yet" : "No expenses yet";

  if (chartData.length === 0) {
    return <div className="flex h-56 items-center justify-center rounded border border-sol-base02 text-sol-base01">{emptyLabel}</div>;
  }

  return (
    <div className="rounded border border-sol-base02 bg-sol-base03 p-3">
      <div className="mb-2">
        <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">{title}</div>
        <div className="text-sol-base01 text-[10px]">Latest period in USD</div>
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <PieChart margin={{ top: 10, right: 20, left: 20, bottom: 5 }}>
          <Pie data={chartData} dataKey="value" nameKey="category" cx="50%" cy="50%" outerRadius={95} label={(props) => {
            const payload = props.payload as { label?: string; allocation?: number } | undefined;
            return (payload?.allocation ?? 0) >= 0.03 ? (payload?.label ?? "") : "";
          }} labelLine={false} isAnimationActive={false}>
            {chartData.map((entry, index) => (
              <Cell key={entry.category} fill={HOLDINGS_PIE_COLORS[index % HOLDINGS_PIE_COLORS.length]} />
            ))}
          </Pie>
          <Tooltip content={<ExpensesPieTooltip />} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

function IncomeStatementCategoriesTable({ item, categories, kind }: { item?: IncomeStatementCategoriesHistoryItem; categories: string[]; kind: "income" | "expenses" }) {
  const rows = useMemo(() => incomeStatementCategoryRows(item, categories, kind), [item, categories, kind]);
  const total = item ? categoryPeriodTotal(item, kind) : 0;
  const title = kind === "income" ? "Income" : "Expenses";
  return (
    <div className="rounded border border-sol-base02 bg-sol-base03 overflow-hidden">
      <div className="border-b border-sol-base02 px-3 py-2">
        <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">{title}</div>
        <div className="text-sol-base01 text-[10px]">Rows are top-level categories</div>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-sol-base01 border-b border-sol-base02 bg-sol-base02/50">
            <th className="text-left font-normal py-1 px-3">Category</th>
            <th className="text-right font-normal py-1 px-3">Amount</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.category} className="hover:bg-sol-base02/50">
              <td className="py-0.5 px-3 text-sol-base0 whitespace-nowrap">{shortName(row.category)}</td>
              <td className="py-0.5 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap">{formatAmount(row.value)}</td>
            </tr>
          ))}
          <tr className="border-t border-sol-base02 bg-sol-base02/40 font-medium">
            <td className="py-1 px-3 text-sol-base1">Total</td>
            <td className="py-1 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap">{formatAmount(total)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function ExpensesOverTimeTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; value: number; color: string; payload?: any }>; label?: string }) {
  if (!active || !payload?.length) return null;
  const totalValue = Number(payload[0]?.payload?.Total || 0);
  const rows = payload.filter((item) => Number(item.value || 0) > 0.005).sort((a, b) => Number(b.value || 0) - Number(a.value || 0));
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
          <span style={{ color: SOL.base0 }}>{shortName(p.name)}: {formatAmount(p.value)} USD</span>
        </div>
      ))}
    </div>
  );
}

function IncomeStatementCategoriesOverTimeChart({ data, categories, kind }: { data: IncomeStatementCategoriesHistoryItem[]; categories: string[]; kind: "income" | "expenses" }) {
  const chartData = useMemo(() => incomeStatementCategoryChartRows(data, categories, kind), [data, categories, kind]);
  const title = kind === "income" ? "Income over time" : "Expenses over time";
  const hasData = chartData.some((row) => categories.some((category) => Math.abs(Number(row[category] || 0)) > 0.005));
  return (
    <div className="relative rounded border border-sol-base02 bg-sol-base03 p-3">
      <div className="mb-2">
        <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">{title}</div>
        <div className="text-sol-base01 text-[10px]">Top-level categories in USD</div>
      </div>
      {!hasData ? (
        <div className="flex h-56 items-center justify-center text-sol-base01">No history yet</div>
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={chartData} margin={{ top: 24, right: 20, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={SOL.base02} />
            <XAxis dataKey="period" tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} />
            <YAxis tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
            <Tooltip content={<ExpensesOverTimeTooltip />} cursor={{ fill: "rgba(147, 161, 161, 0.15)" }} />
            {categories.map((category, index) => (
              <Bar key={category} dataKey={category} stackId={kind} fill={ACCOUNT_COLORS[index % ACCOUNT_COLORS.length]} isAnimationActive={false} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

function IncomeStatementCategoriesPeriodTable({ data, categories, kind }: { data: IncomeStatementCategoriesHistoryItem[]; categories: string[]; kind: "income" | "expenses" }) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const latestPeriod = data[data.length - 1]?.period || "";
  const periodKey = useMemo(() => data.map((item) => item.period).join("|"), [data]);
  const [sortColumn, setSortColumn] = useState(latestPeriod);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const effectiveSortColumn = data.some((item) => item.period === sortColumn) ? sortColumn : latestPeriod;
  const rows = useMemo(() => incomeStatementCategoryPeriodTableRows(data, categories, kind, effectiveSortColumn, sortDir), [data, categories, kind, effectiveSortColumn, sortDir]);
  const totals = useMemo(() => incomeStatementCategoryPeriodTotals(data, kind), [data, kind]);
  const title = kind === "income" ? "Income history" : "Expenses history";

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    const frame = requestAnimationFrame(() => { container.scrollLeft = container.scrollWidth - container.clientWidth; });
    return () => cancelAnimationFrame(frame);
  }, [periodKey]);

  const handleSort = (period: string) => {
    if (period === effectiveSortColumn) setSortDir((dir) => dir === "desc" ? "asc" : "desc");
    else { setSortColumn(period); setSortDir("desc"); }
  };

  return (
    <div className="rounded border border-sol-base02 bg-sol-base03 overflow-hidden">
      <div className="border-b border-sol-base02 px-3 py-2">
        <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">{title}</div>
        <div className="text-sol-base01 text-[10px]">Rows are top-level categories; columns are periods</div>
      </div>
      {data.length === 0 || categories.length === 0 ? (
        <div className="px-3 py-8 text-center text-sol-base01">No history yet</div>
      ) : (
        <div ref={scrollRef} className="overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead>
              <tr className="text-sol-base01 border-b border-sol-base02 bg-sol-base02/50">
                <th className="sticky left-0 z-10 bg-sol-base02 text-left font-normal py-1 px-3 whitespace-nowrap">Category</th>
                {data.map((item) => (
                  <th key={item.period} className="text-right font-normal py-1 px-3 whitespace-nowrap">
                    <button onClick={() => handleSort(item.period)} className="cursor-pointer hover:text-sol-base0">
                      {formatPeriodLabel(item.period)} {effectiveSortColumn === item.period ? (sortDir === "desc" ? "↓" : "↑") : ""}
                    </button>
                  </th>
                ))}
                <th className="text-right font-normal py-1 px-3 whitespace-nowrap border-l border-sol-base02 text-sol-base0">Range Σ</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.category} className="hover:bg-sol-base02/50">
                  <td className="sticky left-0 z-10 bg-sol-base03 py-0.5 px-3 text-sol-base0 whitespace-nowrap">{shortName(row.category)}</td>
                  {data.map((item) => (
                    <td key={item.period} className="py-0.5 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap">{formatAmount(row.values[item.period] || 0)}</td>
                  ))}
                  <td className="py-0.5 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap border-l border-sol-base02 font-medium">{formatAmount(sumPeriodValues(row.values))}</td>
                </tr>
              ))}
              <tr className="border-t border-sol-base02 bg-sol-base02/40 font-medium">
                <td className="sticky left-0 z-10 bg-sol-base02 py-1 px-3 text-sol-base1 whitespace-nowrap">Total</td>
                {data.map((item) => (
                  <td key={item.period} className="py-1 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap">{formatAmount(totals[item.period] || 0)}</td>
                ))}
                <td className="py-1 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap border-l border-sol-base02">{formatAmount(sumPeriodValues(totals))}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function IncomeStatementCategoriesChartView({ data, kind }: { data: IncomeStatementCategoriesHistoryItem[]; kind: "income" | "expenses" }) {
  const categories = useMemo(() => buildIncomeStatementCategorySeries(data, kind), [data, kind]);
  return <IncomeStatementCategoriesOverTimeChart data={data} categories={categories} kind={kind} />;
}

function IncomeStatementCategoriesTableView({ data, kind }: { data: IncomeStatementCategoriesHistoryItem[]; kind: "income" | "expenses" }) {
  const categories = useMemo(() => buildIncomeStatementCategorySeries(data, kind), [data, kind]);
  return <IncomeStatementCategoriesPeriodTable data={data} categories={categories} kind={kind} />;
}

function sumPeriodValues(values: Record<string, number>): number {
  return Object.values(values).reduce((sum, value) => sum + (value || 0), 0);
}

function incomeStatementMetricRows(data: IncomeStatementHistoryItem[], chartTab: ISChartTab, sortColumn: string, sortDir: "asc" | "desc") {
  const metricRows = [
    {
      metric: "Net Profit",
      values: Object.fromEntries(data.map((item) => [item.period, incomeUsdValue(item.income) - balanceUsdValue(item.expenses)])),
    },
    {
      metric: "Income",
      values: Object.fromEntries(data.map((item) => [item.period, incomeUsdValue(item.income)])),
    },
    {
      metric: "Expenses",
      values: Object.fromEntries(data.map((item) => [item.period, balanceUsdValue(item.expenses)])),
    },
  ];
  if (chartTab === "net-profit") return metricRows;
  const rows = metricRows.filter((row) => row.metric.toLowerCase() === chartTab);
  return rows.sort((a, b) => {
    const delta = (a.values[sortColumn] || 0) - (b.values[sortColumn] || 0);
    return sortDir === "asc" ? delta : -delta;
  });
}

function IncomeStatementHistoryTable({ data, chartTab }: { data: IncomeStatementHistoryItem[]; chartTab: ISChartTab }) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const latestPeriod = data[data.length - 1]?.period || "";
  const periodKey = useMemo(() => data.map((item) => item.period).join("|"), [data]);
  const [sortColumn, setSortColumn] = useState(latestPeriod);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const effectiveSortColumn = data.some((item) => item.period === sortColumn) ? sortColumn : latestPeriod;
  const rows = useMemo(() => incomeStatementMetricRows(data, chartTab, effectiveSortColumn, sortDir), [data, chartTab, effectiveSortColumn, sortDir]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    const frame = requestAnimationFrame(() => { container.scrollLeft = container.scrollWidth - container.clientWidth; });
    return () => cancelAnimationFrame(frame);
  }, [periodKey]);

  const handleSort = (period: string) => {
    if (period === effectiveSortColumn) setSortDir((dir) => dir === "desc" ? "asc" : "desc");
    else { setSortColumn(period); setSortDir("desc"); }
  };

  const title = chartTab === "net-profit" ? "Net Profit history" : chartTab === "income" ? "Income history" : "Expenses history";
  const subtitle = chartTab === "net-profit" ? "Rows are net profit, income, and expenses; columns are periods" : "Rows are totals; columns are periods";

  return (
    <div className="rounded border border-sol-base02 bg-sol-base03 overflow-hidden">
      <div className="border-b border-sol-base02 px-3 py-2">
        <div className="text-sol-base1 text-xs font-medium uppercase tracking-wide">{title}</div>
        <div className="text-sol-base01 text-[10px]">{subtitle}</div>
      </div>
      {data.length === 0 ? (
        <div className="px-3 py-8 text-center text-sol-base01">No history yet</div>
      ) : (
        <div ref={scrollRef} className="overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead>
              <tr className="text-sol-base01 border-b border-sol-base02 bg-sol-base02/50">
                <th className="sticky left-0 z-10 bg-sol-base02 text-left font-normal py-1 px-3 whitespace-nowrap">Metric</th>
                {data.map((item) => (
                  <th key={item.period} className="text-right font-normal py-1 px-3 whitespace-nowrap">
                    <button onClick={() => handleSort(item.period)} className="cursor-pointer hover:text-sol-base0">
                      {formatPeriodLabel(item.period)} {effectiveSortColumn === item.period ? (sortDir === "desc" ? "↓" : "↑") : ""}
                    </button>
                  </th>
                ))}
                <th className="text-right font-normal py-1 px-3 whitespace-nowrap border-l border-sol-base02 text-sol-base0">Range Σ</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.metric} className="hover:bg-sol-base02/50">
                  <td className="sticky left-0 z-10 bg-sol-base03 py-0.5 px-3 text-sol-base0 whitespace-nowrap">{row.metric}</td>
                  {data.map((item) => (
                    <td key={item.period} className="py-0.5 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap">{formatAmount(row.values[item.period] || 0)}</td>
                  ))}
                  <td className="py-0.5 px-3 text-right tabular-nums text-sol-base1 whitespace-nowrap border-l border-sol-base02 font-medium">{formatAmount(sumPeriodValues(row.values))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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

function IncomeStatementChart({ data, categoryData, chartTab, onChartTabChange }: { data: IncomeStatementHistoryItem[]; categoryData?: IncomeStatementCategoriesHistoryItem[]; chartTab: ISChartTab; onChartTabChange: (v: ISChartTab) => void }) {
  const chartData = useMemo(() =>
    data.map((item) => {
      const income = incomeUsdValue(item.income);
      const expenses = balanceUsdValue(item.expenses);
      return {
        period: formatPeriodLabel(item.period),
        rawPeriod: item.period,
        Income: income,
        Expenses: expenses,
        "Net Profit": income - expenses,
      };
    }),
    [data]
  );

  return (
    <div className="relative">
      {(chartTab === "income" || chartTab === "expenses") && categoryData ? (
        <IncomeStatementCategoriesChartView data={categoryData} kind={chartTab} />
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          {chartTab === "net-profit" ? (
          <ComposedChart data={chartData} margin={{ top: 10, right: 20, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={SOL.base02} />
            <XAxis dataKey="period" tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} />
            <YAxis tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} tickFormatter={(v) => `${(Math.abs(v) / 1000).toFixed(0)}k`} />
            <Tooltip content={<NetProfitTooltip />} cursor={{ fill: "rgba(147, 161, 161, 0.15)" }} />
            <Bar dataKey="Income" fill={SOL.green} isAnimationActive={false} />
            <Bar dataKey="Expenses" fill={SOL.red} isAnimationActive={false} />
            <Line type="monotone" dataKey="Net Profit" stroke={SOL.blue} strokeWidth={2} dot={false} isAnimationActive={false} />
          </ComposedChart>
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
      )}
      <div className="flex justify-center gap-1 mt-1">
        {([["net-profit", "Net Profit"], ["income", "Income"], ["expenses", "Expenses"]] as const).map(([t, label]) => (
          <button
            key={t}
            onClick={() => onChartTabChange(t)}
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
  const [mode, setMode] = useState<ViewMode>(initialMode);
  const [granularity, setGranularity] = useState<SharedGranularity>(initialGranularity);
  const [holdingsRiskyOnly, setHoldingsRiskyOnly] = useState<boolean>(() => localStorage.getItem("holdings-risky-only") === "1");
  const [isChartTab, setIsChartTab] = useState<ISChartTab>(() => (localStorage.getItem("finance-is-chart-tab") as ISChartTab) || "income");
  const vmQuery = vmName ? `&vm_name=${encodeURIComponent(vmName)}` : "";
  const vmQueryOnly = vmName ? `?vm_name=${encodeURIComponent(vmName)}` : "";

  useEffect(() => {
    localStorage.setItem("finance-mode", mode);
  }, [mode]);

  useEffect(() => {
    localStorage.setItem("finance-granularity", granularity);
  }, [granularity]);

  const activeMode = isModeTab(tab) ? mode : "over-time";
  const isLiveMode = isModeTab(tab) && activeMode === "live";
  const isOverTimeMode = isModeTab(tab) && activeMode === "over-time";
  const showsTimeInput = tab === "fire" || isOverTimeMode || (tab === "income-statement" && isLiveMode);
  const showsGranularity = tab === "fire" || isOverTimeMode;

  const handleModeChange = (v: ViewMode) => {
    if (!isModeTab(tab)) return;
    setMode(v);
  };

  const handleGranularityChange = (v: SharedGranularity) => {
    setGranularity(v);
  };

  const commitTimeInput = () => {
    const v = timeInput.trim();
    setCommittedTime(v);
    localStorage.setItem("finance-time", v);
  };

  const handleHoldingsRiskyOnlyChange = (v: boolean) => {
    setHoldingsRiskyOnly(v);
    localStorage.setItem("holdings-risky-only", v ? "1" : "0");
  };

  const handleIncomeStatementChartTabChange = (v: ISChartTab) => {
    setIsChartTab(v);
    localStorage.setItem("finance-is-chart-tab", v);
  };

  const bsKey = tab === "balance-sheet" && mode === "live"
    ? `${API}/api/finance/balance-sheet?time=&convert=USD${vmQuery}`
    : null;

  const isKey = tab === "income-statement" && mode === "live"
    ? `${API}/api/finance/income-statement?time=${encodeURIComponent(committedTime)}${vmQuery}`
    : null;

  const holdingsKey = tab === "holdings" && mode === "live"
    ? `${API}/api/finance/holdings${vmQueryOnly}${vmQueryOnly ? "&" : "?"}risky_only=${holdingsRiskyOnly ? "true" : "false"}`
    : null;

  const transactionsKey = tab === "transactions"
    ? `${API}/api/finance/transactions${vmQueryOnly}`
    : null;

  const fireKey = tab === "fire"
    ? `${API}/api/finance/fire-progress${vmQueryOnly}`
    : null;

  const bsHistKey = (tab === "balance-sheet" && mode === "over-time") || tab === "fire"
    ? `${API}/api/finance/balance-sheet?history=true&granularity=${granularity}&convert=USD&time=${encodeURIComponent(committedTime)}${vmQuery}`
    : null;

  const bsPositionsHistKey = tab === "balance-sheet" && mode === "over-time"
    ? `${API}/api/finance/balance-sheet?history=true&breakdown=positions&granularity=${granularity}&convert=USD&time=${encodeURIComponent(committedTime)}${vmQuery}`
    : null;

  const isHistKey = tab === "income-statement" && mode === "over-time"
    ? `${API}/api/finance/income-statement?history=true&granularity=${granularity}&convert=USD&time=${encodeURIComponent(committedTime)}${vmQuery}`
    : null;

  const expensesCatHistKey = tab === "income-statement" && mode === "over-time" && (isChartTab === "income" || isChartTab === "expenses")
    ? `${API}/api/finance/income-statement?history=true&breakdown=categories&granularity=${granularity}&convert=USD&time=${encodeURIComponent(committedTime)}${vmQuery}`
    : null;

  const bs = useFinanceEnvelope<BalanceSheetData>(bsKey);
  const is = useFinanceEnvelope<IncomeStatementData>(isKey);
  const holdings = useFinanceEnvelope<HoldingPosition[]>(holdingsKey);
  const transactions = useFinanceEnvelope<TransactionRow[]>(transactionsKey);
  const fire = useFinanceEnvelope<FireProgressData>(fireKey);
  const bsHist = useFinanceEnvelope<BalanceSheetHistoryItem[]>(bsHistKey);
  const bsPositionsHist = useFinanceEnvelope<BalanceSheetPositionsHistoryItem[]>(bsPositionsHistKey);
  const isHist = useFinanceEnvelope<IncomeStatementHistoryItem[]>(isHistKey);
  const expensesCatHist = useFinanceEnvelope<IncomeStatementCategoriesHistoryItem[]>(expensesCatHistKey);

  const bsData = bs.data?.data;
  const isData = is.data?.data;
  const displayIsData = useMemo(() => isData ? {
    income: mapAccountBalances(isData.income, (amount) => Math.abs(amount)),
    expenses: isData.expenses,
  } : undefined, [isData]);
  const holdingsData = holdings.data?.data;
  const transactionsData = transactions.data?.data;
  const fireData = fire.data?.data;
  const bsHistData = bsHist.data?.data;
  const bsPositionsHistData = bsPositionsHist.data?.data || [];
  const isHistData = isHist.data?.data;
  const expensesCatHistData = expensesCatHist.data?.data;
  const holdingRows = useMemo(() => holdingsData ? toHoldingRows(holdingsData) : [], [holdingsData]);

  const activeEnvelope = tab === "transactions" ? transactions.data : tab === "holdings" ? holdings.data : tab === "balance-sheet" ? (bs.data || bsHist.data) : tab === "income-statement" ? (is.data || isHist.data) : fire.data;

  const mutateActive = async () => {
    await Promise.all([bs.mutate(), is.mutate(), holdings.mutate(), transactions.mutate(), fire.mutate(), bsHist.mutate(), bsPositionsHist.mutate(), isHist.mutate(), expensesCatHist.mutate()]);
  };

  const refreshSnapshots = async () => {
    const res = await authFetch(`${API}/api/finance/refresh${vmQueryOnly}`, { method: "POST" });
    if (!res.ok) throw new Error("Failed to refresh finance data");
    await mutateActive();
  };

  const tableLoading = tab === "balance-sheet" ? (isLiveMode ? bs.isLoading : bsHist.isLoading) : tab === "income-statement" ? (isLiveMode ? is.isLoading : isHist.isLoading) : tab === "fire" ? fire.isLoading : tab === "transactions" ? transactions.isLoading : holdings.isLoading;
  const chartLoading = tab === "balance-sheet" && isOverTimeMode ? bsPositionsHist.isLoading : tab === "fire" ? bsHist.isLoading : tab === "income-statement" && isOverTimeMode && (isChartTab === "income" || isChartTab === "expenses") ? expensesCatHist.isLoading : false;
  const loading = tableLoading && chartLoading;

  const tableError = tab === "balance-sheet" ? (isLiveMode ? bs.error : bsHist.error) : tab === "income-statement" ? (isLiveMode ? is.error : isHist.error) : tab === "fire" ? fire.error : tab === "transactions" ? transactions.error : holdings.error;
  const chartError = tab === "balance-sheet" && isOverTimeMode ? bsPositionsHist.error : tab === "fire" ? bsHist.error : tab === "income-statement" && isOverTimeMode && (isChartTab === "income" || isChartTab === "expenses") ? (expensesCatHist.error && !isAbortError(expensesCatHist.error) ? expensesCatHist.error : null) : null;
  const error = tableError && chartError;

  return (
    <div className="h-full overflow-y-auto bg-sol-base03 text-sm">
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
          {isModeTab(tab) ? <ModeToggle value={activeMode} onChange={handleModeChange} /> : null}
          {showsTimeInput ? (
            <input
              type="text"
              value={timeInput}
              onChange={(e) => setTimeInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") commitTimeInput(); }}
              onBlur={commitTimeInput}
              placeholder="month, 2024, 2024-q2, day-1 - day"
              className="px-2 py-1 rounded text-xs w-56 bg-sol-base02 text-sol-base1 border border-sol-base01 outline-none placeholder:text-sol-base01"
            />
          ) : null}
          {showsGranularity ? <SharedGranularityToggle value={granularity} onChange={handleGranularityChange} /> : null}
        </div>
        <div className="flex justify-center gap-1">
          {([["balance-sheet", "Balance Sheet"], ["holdings", "Holdings"], ["income-statement", "Income Statement"], ["transactions", "Transactions"], ["fire", "FIRE"]] as const).map(([t, label]) => (
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

      <div className="px-1 py-2">
        {loading ? (
          <p className="text-sol-base01 italic px-3">Loading...</p>
        ) : error ? (
          <p className="text-sol-red px-3">Error loading data</p>
        ) : tab === "balance-sheet" ? (
          isLiveMode ? (
            bs.isLoading ? (
              <p className="text-sol-base01 italic px-3">Loading...</p>
            ) : bsData ? (
              <div className="space-y-3">
                <BalanceSheetLivePieCharts assets={bsData.assets} liabilities={bsData.liabilities} />
                <div className="flex gap-2 min-w-0">
                  <div className="flex-1 min-w-0">
                    <AccountTree root={bsData.assets} title="Assets" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <AccountTree root={bsData.liabilities} title="Liabilities" />
                    <EquitySummary assets={bsData.assets} liabilities={bsData.liabilities} />
                  </div>
                </div>
              </div>
            ) : null
          ) : (
            <div className="space-y-3">
              {bsHist.isLoading ? (
                <p className="text-sol-base01 italic px-3 mb-2">Loading chart...</p>
              ) : bsHist.error ? null : bsHistData ? (
                <BalanceSheetChart data={bsHistData} />
              ) : null}
              {bsPositionsHist.isLoading ? (
                <p className="text-sol-base01 italic px-3">Loading positions...</p>
              ) : bsPositionsHist.error && !isAbortError(bsPositionsHist.error) ? (
                <p className="text-sol-red px-3">Error loading positions history</p>
              ) : (
                <BalanceSheetOverTimeTable data={bsPositionsHistData} />
              )}
            </div>
          )
        ) : tab === "income-statement" ? (
          isLiveMode ? (
            is.isLoading ? (
              <p className="text-sol-base01 italic px-3">Loading...</p>
            ) : displayIsData ? (
              <div className="space-y-3">
                <IncomeStatementLivePieCharts income={displayIsData.income} expenses={displayIsData.expenses} />
                <div className="flex gap-2 min-w-0">
                  <div className="flex-1 min-w-0">
                    <AccountTree root={displayIsData.income} title="Income" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <AccountTree root={displayIsData.expenses} title="Expenses" />
                    <NetIncomeSummary income={displayIsData.income} expenses={displayIsData.expenses} />
                  </div>
                </div>
              </div>
            ) : null
          ) : (
            isHist.isLoading ? (
              <p className="text-sol-base01 italic px-3 mb-2">Loading chart...</p>
            ) : isHist.error ? null : isHistData ? (
              <IncomeStatementOverTimeView data={isHistData} categoryData={expensesCatHistData} categoryState={expensesCatHist} chartTab={isChartTab} onChartTabChange={handleIncomeStatementChartTabChange} />
            ) : null
          )
        ) : tab === "holdings" ? (
          mode === "over-time" ? (
            <AssetsOverTimeView vmName={vmName} riskyOnly={holdingsRiskyOnly} onRiskyOnlyChange={handleHoldingsRiskyOnlyChange} time={committedTime} granularity={granularity} />
          ) : (
            holdings.isLoading ? (
              <p className="text-sol-base01 italic px-3">Loading...</p>
            ) : holdingsData ? (
              <>
                <HoldingsPieChart positions={holdingsData} />
                <div className="flex items-center justify-between gap-3 px-2 py-3">
                  <RiskyAllocationSummary summary={holdings.data?.summary} loading={holdings.isLoading} />
                </div>
                <HoldingsTable holdings={holdingRows} totals={holdingTotals(holdingRows)} syncedAt={holdings.data?.synced_at} riskyOnly={holdingsRiskyOnly} onRiskyOnlyChange={handleHoldingsRiskyOnlyChange} vmName={vmName} />
              </>
            ) : null
          )
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
                <BalanceSheetChart data={bsHistData} targetLine={fireData?.target_usd} />
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}
