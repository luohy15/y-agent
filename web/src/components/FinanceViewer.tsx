import { useState, useMemo } from "react";
import useSWR from "swr";
import { API, authFetch, clearToken } from "../api";

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

function formatAmount(amount: number): string {
  return (amount === 0 ? 0 : amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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

interface FinanceViewerProps {
  vmName?: string | null;
}

export default function FinanceViewer({ vmName }: FinanceViewerProps) {
  const [tab, setTab] = useState<Tab>(() => (localStorage.getItem("finance-tab") as Tab) || "balance-sheet");
  const [timeInput, setTimeInput] = useState(() => localStorage.getItem("finance-time") || "year");
  const [committedTime, setCommittedTime] = useState(() => localStorage.getItem("finance-time") || "year");
  const vmQuery = vmName ? `&vm_name=${encodeURIComponent(vmName)}` : "";

  const bsKey = tab === "balance-sheet"
    ? `${API}/api/finance/balance-sheet?convert=USD${vmQuery}`
    : null;

  const isKey = tab === "income-statement"
    ? `${API}/api/finance/income-statement?time=${encodeURIComponent(committedTime)}${vmQuery}`
    : null;

  const vmQueryHoldings = vmName ? `?vm_name=${encodeURIComponent(vmName)}` : "";
  const holdingsKey = tab === "holdings"
    ? `${API}/api/finance/holdings${vmQueryHoldings}`
    : null;

  const posKey = tab === "position"
    ? `${API}/api/finance/position?convert=USD${vmQuery}`
    : null;

  const { data: bsData, isLoading: bsLoading, error: bsError } = useSWR<BalanceSheetData>(bsKey, fetcher, { revalidateOnFocus: false });
  const { data: isData, isLoading: isLoading, error: isError } = useSWR<IncomeStatementData>(isKey, fetcher, { revalidateOnFocus: false });
  const { data: holdingsData, isLoading: holdingsLoading, error: holdingsError } = useSWR<HoldingsData>(holdingsKey, fetcher, { revalidateOnFocus: false });
  const { data: posData, isLoading: posLoading, error: posError } = useSWR<PositionData>(posKey, fetcher, { revalidateOnFocus: false });

  const loading = tab === "balance-sheet" ? bsLoading : tab === "income-statement" ? isLoading : tab === "holdings" ? holdingsLoading : posLoading;
  const error = tab === "balance-sheet" ? bsError : tab === "income-statement" ? isError : tab === "holdings" ? holdingsError : posError;

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
        ) : tab === "balance-sheet" && bsData ? (
          <div className="flex gap-2">
            <div className="flex-1 min-w-0">
              <AccountTree root={bsData.assets} title="Assets" />
            </div>
            <div className="flex-1 min-w-0">
              <AccountTree root={bsData.liabilities} title="Liabilities" />
              <EquitySummary assets={bsData.assets} liabilities={bsData.liabilities} />
            </div>
          </div>
        ) : tab === "income-statement" && isData ? (
          <div className="flex gap-2">
            <div className="flex-1 min-w-0">
              <AccountTree root={isData.income} title="Income" />
            </div>
            <div className="flex-1 min-w-0">
              <AccountTree root={isData.expenses} title="Expenses" />
            </div>
          </div>
        ) : tab === "holdings" && holdingsData ? (
          <HoldingsTable holdings={holdingsData.rows} totals={holdingsData.totals} />
        ) : tab === "position" && posData ? (
          <div className="flex justify-center">
            <div className="w-full max-w-md">
              <PositionView data={posData} />
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
