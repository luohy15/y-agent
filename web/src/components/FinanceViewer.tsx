import { useState, useMemo } from "react";
import useSWR from "swr";
import { API, authFetch, clearToken } from "../api";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
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

interface PositionData {
  net_worth: number;
  stock_holdings: number;
  labor_income_12m: number;
  monthly_expense: number;
  living_reserve: number;
  liability_allowance: number;
  max_investable: number;
  position_ratio: number;
  currency: string;
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

const fetcher = async (url: string) => {
  const res = await authFetch(url);
  if (res.status === 401) {
    clearToken();
    throw new Error("Unauthorized");
  }
  return res.json();
};

type Tab = "balance-sheet" | "income-statement" | "holdings" | "position";

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

const STOCK_COLORS = [SOL.blue, SOL.green, SOL.red, SOL.yellow, SOL.cyan, SOL.magenta, SOL.violet, SOL.orange];

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

function PositionView({ data }: { data: PositionData }) {
  const rows: [string, string][] = [
    ["Net Worth", `${formatAmount(data.net_worth)} ${data.currency}`],
    ["Stock Holdings", `${formatAmount(data.stock_holdings)} ${data.currency}`],
    ["Labor Income (12m)", `${formatAmount(data.labor_income_12m)} ${data.currency}`],
    ["Monthly Expense", `${formatAmount(data.monthly_expense)} ${data.currency}`],
    ["Living Reserve", `${formatAmount(data.living_reserve)} ${data.currency}`],
    ["Liability Allowance", `${formatAmount(data.liability_allowance)} ${data.currency}`],
    ["Max Investable", `${formatAmount(data.max_investable)} ${data.currency}`],
    ["Position Ratio", `${(data.position_ratio * 100).toFixed(1)}%`],
  ];

  return (
    <div className="mb-4">
      <div className="px-3 py-1.5 bg-sol-base02/50 border-b border-sol-base02">
        <span className="text-sol-base1 font-medium text-xs uppercase tracking-wide">Position</span>
      </div>
      <table className="w-full text-sm">
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label} className="hover:bg-sol-base02/50">
              <td className="py-1 px-3 text-sol-base01">{label}</td>
              <td className="py-1 px-3 text-right tabular-nums text-sol-base0">{value}</td>
            </tr>
          ))}
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

function BalanceSheetChart({ data, granularity, onGranularityChange }: { data: BalanceSheetHistoryItem[]; granularity: Granularity; onGranularityChange: (v: Granularity) => void }) {
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
          <Line type="linear" dataKey="Net Worth" stroke={SOL.green} dot={false} strokeWidth={2} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
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

function HoldingsChart({ data }: { data: Record<string, { date: string; price: number }[]> }) {
  const { chartData, symbols } = useMemo(() => {
    const symbols = Object.keys(data).sort();
    if (symbols.length === 0) return { chartData: [], symbols: [] };

    // Collect all unique dates
    const dateSet = new Set<string>();
    for (const sym of symbols) {
      for (const pt of data[sym]) dateSet.add(pt.date);
    }
    const dates = [...dateSet].sort();

    // Build first price lookup
    const firstPrice: Record<string, number> = {};
    for (const sym of symbols) {
      if (data[sym].length > 0) firstPrice[sym] = data[sym][0].price;
    }

    // Build price lookup per symbol
    const priceLookup: Record<string, Record<string, number>> = {};
    for (const sym of symbols) {
      priceLookup[sym] = {};
      for (const pt of data[sym]) {
        priceLookup[sym][pt.date] = pt.price;
      }
    }

    // Build chart data with normalized % change
    const chartData: Record<string, string | number>[] = [];
    const lastKnown: Record<string, number> = {};
    for (const date of dates) {
      const row: Record<string, string | number> = { date: formatPeriodLabel(date.slice(0, 7)), rawPeriod: date.slice(0, 7) };
      for (const sym of symbols) {
        if (priceLookup[sym][date] !== undefined) {
          lastKnown[sym] = priceLookup[sym][date];
        }
        if (lastKnown[sym] !== undefined && firstPrice[sym]) {
          row[sym] = parseFloat(((lastKnown[sym] / firstPrice[sym] - 1) * 100).toFixed(2));
        }
      }
      chartData.push(row);
    }

    return { chartData, symbols };
  }, [data]);

  if (symbols.length === 0) {
    return <p className="text-sol-base01 italic px-3">No price history data available</p>;
  }

  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={chartData} margin={{ top: 10, right: 20, left: 20, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={SOL.base02} />
        <XAxis dataKey="date" tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} />
        <YAxis tick={{ fill: SOL.base0, fontSize: 11 }} stroke={SOL.base02} tickFormatter={(v) => `${v}%`} />
        <Tooltip content={<ChartTooltipContent formatter={(v) => `${v.toFixed(2)}%`} />} />
        <Legend wrapperStyle={{ color: SOL.base0, fontSize: 12 }} />
        {symbols.map((sym, i) => (
          <Line key={sym} type="monotone" dataKey={sym} stroke={STOCK_COLORS[i % STOCK_COLORS.length]} dot={false} strokeWidth={1.5} />
        ))}
      </LineChart>
    </ResponsiveContainer>
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

  const posKey = tab === "position"
    ? `${API}/api/finance/position?convert=USD${vmQuery}`
    : null;

  // Chart data fetches (also always fetch for active tab, except position)
  const bsHistKey = tab === "balance-sheet"
    ? `${API}/api/finance/balance-sheet?history=true&granularity=${granularity}&convert=USD&time=${encodeURIComponent(committedTime)}${vmQuery}`
    : null;

  const isHistKey = tab === "income-statement"
    ? `${API}/api/finance/income-statement?history=true&granularity=${granularity}&convert=USD&time=${encodeURIComponent(committedTime)}${vmQuery}`
    : null;

  const priceHistKey = tab === "holdings"
    ? `${API}/api/finance/price-history${vmQueryOnly}`
    : null;

  const { data: bsData, isLoading: bsLoading, error: bsError } = useSWR<BalanceSheetData>(bsKey, fetcher, { revalidateOnFocus: false });
  const { data: isData, isLoading: isLoading, error: isError } = useSWR<IncomeStatementData>(isKey, fetcher, { revalidateOnFocus: false });
  const { data: holdingsData, isLoading: holdingsLoading, error: holdingsError } = useSWR<HoldingsData>(holdingsKey, fetcher, { revalidateOnFocus: false });
  const { data: posData, isLoading: posLoading, error: posError } = useSWR<PositionData>(posKey, fetcher, { revalidateOnFocus: false });

  const { data: bsHistData, isLoading: bsHistLoading, error: bsHistError } = useSWR<BalanceSheetHistoryItem[]>(bsHistKey, fetcher, { revalidateOnFocus: false });
  const { data: isHistData, isLoading: isHistLoading, error: isHistError } = useSWR<IncomeStatementHistoryItem[]>(isHistKey, fetcher, { revalidateOnFocus: false });
  const { data: priceHistData, isLoading: priceHistLoading, error: priceHistError } = useSWR<Record<string, { date: string; price: number }[]>>(priceHistKey, fetcher, { revalidateOnFocus: false });

  // Combined loading/error: table OR chart loading
  const tableLoading = tab === "balance-sheet" ? bsLoading : tab === "income-statement" ? isLoading : tab === "holdings" ? holdingsLoading : posLoading;
  const chartLoading = tab === "balance-sheet" ? bsHistLoading : tab === "income-statement" ? isHistLoading : tab === "holdings" ? priceHistLoading : false;
  const loading = tableLoading && chartLoading;

  const tableError = tab === "balance-sheet" ? bsError : tab === "income-statement" ? isError : tab === "holdings" ? holdingsError : posError;
  const chartError = tab === "balance-sheet" ? bsHistError : tab === "income-statement" ? isHistError : tab === "holdings" ? priceHistError : null;
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
          {([["balance-sheet", "Balance Sheet"], ["income-statement", "Income Statement"], ["holdings", "Holdings"], ["position", "Position"]] as const).map(([t, label]) => (
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
          <>
            {priceHistLoading ? (
              <p className="text-sol-base01 italic px-3 mb-2">Loading chart...</p>
            ) : priceHistError ? null : priceHistData ? (
              <div className="mb-3"><HoldingsChart data={priceHistData} /></div>
            ) : null}
            {holdingsLoading ? (
              <p className="text-sol-base01 italic px-3">Loading...</p>
            ) : holdingsData ? (
              <HoldingsTable holdings={holdingsData.rows} totals={holdingsData.totals} />
            ) : null}
          </>
        ) : tab === "position" && posData ? (
          <div className="flex justify-center">
            <div className="w-full max-w-md">
              <PositionView data={posData} />
            </div>
          </div>
        ) : posLoading ? (
          <p className="text-sol-base01 italic px-3">Loading...</p>
        ) : null}
      </div>
    </div>
  );
}
