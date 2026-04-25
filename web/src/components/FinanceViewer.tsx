import { useState, useMemo } from "react";
import useSWR from "swr";
import { API, jsonFetcher as fetcher } from "../api";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
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
  unrealized_profit_pct: number | null;
}

interface HoldingTotalRow {
  book_value: HoldingAmount | [];
  market_value: HoldingAmount | [];
  unrealized_profit_pct: number | null;
}

interface HoldingsData {
  rows: HoldingRow[];
  totals: HoldingTotalRow[];
}

type Tab = "balance-sheet" | "income-statement" | "holdings" | "fire";

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
  config_source: "file" | "default";
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
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[parseInt(month, 10) - 1]} ${fullYear ? year : year.slice(2)}`;
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

type HoldingSortKey = "asset" | "units" | "avg_cost" | "price" | "book_value" | "market_value" | "pnl";
type SortDir = "asc" | "desc";

function getNumericVal(v: HoldingAmount | number | null | []): number {
  if (v == null || Array.isArray(v)) return 0;
  return typeof v === "number" ? v : v.number;
}

function holdingSortValue(h: HoldingRow, key: HoldingSortKey): string | number {
  switch (key) {
    case "asset": return (h.units as HoldingAmount).currency;
    case "units": return (h.units as HoldingAmount).number;
    case "avg_cost": return getNumericVal(h.average_cost);
    case "price": return getNumericVal(h.price);
    case "book_value": return getNumericVal(h.book_value);
    case "market_value": return getNumericVal(h.market_value);
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

function HoldingsTable({ holdings, totals }: { holdings: HoldingRow[]; totals: HoldingTotalRow[] }) {
  const [sortKey, setSortKey] = useState<HoldingSortKey>(() => (localStorage.getItem("holdings-sort-key") as HoldingSortKey) || "market_value");
  const [sortDir, setSortDir] = useState<SortDir>(() => (localStorage.getItem("holdings-sort-dir") as SortDir) || "desc");

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

  // Filter out rows with empty/invalid units (e.g. units is [] or null)
  const valid = holdings.filter((h) => isValidAmount(h.units));

  const sorted = useMemo(() => {
    const copy = [...valid];
    copy.sort((a, b) => {
      const av = holdingSortValue(a, sortKey);
      const bv = holdingSortValue(b, sortKey);
      let cmp: number;
      if (typeof av === "string" && typeof bv === "string") cmp = av.localeCompare(bv);
      else cmp = (av as number) - (bv as number);
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [valid, sortKey, sortDir]);

  const hp = { currentKey: sortKey, dir: sortDir, onSort: handleSort };

  return (
    <div className="mb-4">
      <div className="px-3 py-1.5 bg-sol-base02/50 border-b border-sol-base02">
        <span className="text-sol-base1 font-medium text-xs uppercase tracking-wide">Holdings</span>
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
            <SortableHeader label="P&L %" sortKey="pnl" align="right" {...hp} />
          </tr>
        </thead>
        <tbody>
          {sorted.map((h, i) => (
            <tr key={i} className="hover:bg-sol-base02/50">
              <td className="py-0.5 px-3 text-sol-base1">{h.units.currency}</td>
              <td className="py-0.5 px-3 text-right tabular-nums text-sol-base0">{formatAmount(h.units.number)}</td>
              <td className="py-0.5 px-3 text-right tabular-nums text-sol-base0">
                {h.average_cost != null ? formatAmount(typeof h.average_cost === "number" ? h.average_cost : h.average_cost.number) : "—"}
              </td>
              <td className="py-0.5 px-3 text-right tabular-nums text-sol-base0">
                {h.price != null ? formatAmount(typeof h.price === "number" ? h.price : h.price.number) : "—"}
              </td>
              <td className="py-0.5 px-3 text-right tabular-nums text-sol-base0">
                {isValidAmount(h.book_value) ? <>{formatAmount(h.book_value.number)} <span className="text-sol-base01 text-xs">{h.book_value.currency}</span></> : "—"}
              </td>
              <td className="py-0.5 px-3 text-right tabular-nums text-sol-base0">
                {isValidAmount(h.market_value) ? <>{formatAmount(h.market_value.number)} <span className="text-sol-base01 text-xs">{h.market_value.currency}</span></> : "—"}
              </td>
              <td className={`py-0.5 px-3 text-right tabular-nums ${(h.unrealized_profit_pct ?? 0) > 0 ? "text-sol-green" : (h.unrealized_profit_pct ?? 0) < 0 ? "text-sol-red" : "text-sol-base0"}`}>
                {h.unrealized_profit_pct != null ? <>{h.unrealized_profit_pct > 0 ? "+" : ""}{formatAmount(h.unrealized_profit_pct)}%</> : "—"}
              </td>
            </tr>
          ))}
          {totals.map((t, i) => {
            const bv = isValidAmount(t.book_value) ? t.book_value : null;
            const mv = isValidAmount(t.market_value) ? t.market_value : null;
            const pct = t.unrealized_profit_pct ?? 0;
            return (
              <tr key={i} className="border-t border-sol-base02 font-medium">
                <td className="py-1 px-3 text-sol-base1" colSpan={4}>Total Stock{totals.length > 1 && bv ? ` (${bv.currency})` : ""}</td>
                <td className="py-1 px-3 text-right tabular-nums text-sol-base0">{bv ? formatAmount(bv.number) : "—"}</td>
                <td className="py-1 px-3 text-right tabular-nums text-sol-base0">{mv ? formatAmount(mv.number) : "—"}</td>
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

type Granularity = "monthly" | "yearly";

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

// --- Chart Components ---

function tooltipLabel(payload: any[] | undefined, fallback?: string): string {
  const raw = payload?.[0]?.payload?.rawPeriod;
  if (raw) return formatPeriodLabel(raw, true);
  return fallback ?? "";
}

function ChartTooltipContent({ active, payload, label, formatter }: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string; payload?: any }>;
  label?: string;
  formatter?: (value: number) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded px-2 py-1.5 text-xs" style={{ background: SOL.base02, border: `1px solid ${SOL.base01}` }}>
      <div style={{ color: SOL.base1 }} className="mb-1">{tooltipLabel(payload, label)}</div>
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full" style={{ background: p.color }} />
          <span style={{ color: SOL.base0 }}>{p.name}: {formatter ? formatter(p.value) : p.value}</span>
        </div>
      ))}
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
      {data.config_source === "default" && (
        <div className="px-3 py-2 rounded text-xs bg-sol-yellow/10 text-sol-yellow border border-sol-yellow/30">
          Using default FIRE target. Edit <code className="px-1 bg-sol-base02/60 rounded">$Y_AGENT_HOME/finance/fire_target.json</code> to customize.
        </div>
      )}

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
          <BarChart data={chartData} margin={{ top: 10, right: 20, left: 20, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={SOL.base02} />
            <XAxis dataKey="period" tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} />
            <YAxis tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} tickFormatter={(v) => `${(Math.abs(v) / 1000).toFixed(0)}k`} />
            <Tooltip content={<NetProfitTooltip />} cursor={{ fill: "rgba(147, 161, 161, 0.15)" }} />
            <Bar dataKey="Income" fill={SOL.green} isAnimationActive={false} />
            <Bar dataKey="Expenses" fill={SOL.red} isAnimationActive={false} />
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
  const vmQuery = vmName ? `&vm_name=${encodeURIComponent(vmName)}` : "";
  const vmQueryOnly = vmName ? `?vm_name=${encodeURIComponent(vmName)}` : "";

  const handleGranularityChange = (v: Granularity) => {
    setGranularity(v);
    localStorage.setItem("finance-granularity", v);
  };

  // Table data fetches (always fetch for active tab)
  const bsKey = tab === "balance-sheet"
    ? `${API}/api/finance/balance-sheet?time=${encodeURIComponent(committedTime)}&convert=USD${vmQuery}`
    : null;

  const isKey = tab === "income-statement"
    ? `${API}/api/finance/income-statement?time=${encodeURIComponent(committedTime)}${vmQuery}`
    : null;

  const holdingsKey = tab === "holdings"
    ? `${API}/api/finance/holdings${vmQueryOnly}`
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

  const { data: bsData, isLoading: bsLoading, error: bsError } = useSWR<BalanceSheetData>(bsKey, fetcher, { revalidateOnFocus: false });
  const { data: isData, isLoading: isLoading, error: isError } = useSWR<IncomeStatementData>(isKey, fetcher, { revalidateOnFocus: false });
  const { data: holdingsData, isLoading: holdingsLoading, error: holdingsError } = useSWR<HoldingsData>(holdingsKey, fetcher, { revalidateOnFocus: false });
  const { data: fireData, isLoading: fireLoading, error: fireError } = useSWR<FireProgressData>(fireKey, fetcher, { revalidateOnFocus: false });

  const { data: bsHistData, isLoading: bsHistLoading, error: bsHistError } = useSWR<BalanceSheetHistoryItem[]>(bsHistKey, fetcher, { revalidateOnFocus: false });
  const { data: isHistData, isLoading: isHistLoading, error: isHistError } = useSWR<IncomeStatementHistoryItem[]>(isHistKey, fetcher, { revalidateOnFocus: false });

  // Combined loading/error: table OR chart loading
  const tableLoading = tab === "balance-sheet" ? bsLoading : tab === "income-statement" ? isLoading : tab === "fire" ? fireLoading : holdingsLoading;
  const chartLoading = tab === "balance-sheet" || tab === "fire" ? bsHistLoading : tab === "income-statement" ? isHistLoading : false;
  const loading = tableLoading && chartLoading;

  const tableError = tab === "balance-sheet" ? bsError : tab === "income-statement" ? isError : tab === "fire" ? fireError : holdingsError;
  const chartError = tab === "balance-sheet" || tab === "fire" ? bsHistError : tab === "income-statement" ? isHistError : null;
  const error = tableError && chartError;

  return (
    <div className="h-full overflow-y-auto bg-sol-base03 text-sm">
      {/* Top bar */}
      <div className="sticky top-0 z-10 bg-sol-base03 border-b border-sol-base02 px-3 py-2 space-y-2">
        <div className="flex items-center justify-end">
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
          {([["balance-sheet", "Balance Sheet"], ["income-statement", "Income Statement"], ["holdings", "Holdings"], ["fire", "FIRE 进度"]] as const).map(([t, label]) => (
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
            {bsHistLoading ? (
              <p className="text-sol-base01 italic px-3 mb-2">Loading chart...</p>
            ) : bsHistError ? null : bsHistData ? (
              <div className="mb-3"><BalanceSheetChart data={bsHistData} granularity={granularity} onGranularityChange={handleGranularityChange} /></div>
            ) : null}
            {bsLoading ? (
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
            {isHistLoading ? (
              <p className="text-sol-base01 italic px-3 mb-2">Loading chart...</p>
            ) : isHistError ? null : isHistData ? (
              <div className="mb-3"><IncomeStatementChart data={isHistData} granularity={granularity} onGranularityChange={handleGranularityChange} /></div>
            ) : null}
            {isLoading ? (
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
          holdingsLoading ? (
            <p className="text-sol-base01 italic px-3">Loading...</p>
          ) : holdingsData ? (
            <HoldingsTable holdings={holdingsData.rows} totals={holdingsData.totals} />
          ) : null
        ) : tab === "fire" ? (
          <>
            {fireLoading ? (
              <p className="text-sol-base01 italic px-3">Loading...</p>
            ) : fireError ? (
              <p className="text-sol-red px-3">Error loading FIRE progress</p>
            ) : fireData ? (
              <div className="px-2"><FireProgressView data={fireData} /></div>
            ) : null}
            {bsHistLoading ? (
              <p className="text-sol-base01 italic px-3 mt-3">Loading chart...</p>
            ) : bsHistError ? null : bsHistData ? (
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
