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

const fetcher = async (url: string) => {
  const res = await authFetch(url);
  if (res.status === 401) {
    clearToken();
    throw new Error("Unauthorized");
  }
  return res.json();
};

type Tab = "balance-sheet" | "income-statement";

function formatAmount(amount: number): string {
  return amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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

  const { data: bsData, isLoading: bsLoading, error: bsError } = useSWR<BalanceSheetData>(bsKey, fetcher, { revalidateOnFocus: false });
  const { data: isData, isLoading: isLoading, error: isError } = useSWR<IncomeStatementData>(isKey, fetcher, { revalidateOnFocus: false });

  const loading = tab === "balance-sheet" ? bsLoading : isLoading;
  const error = tab === "balance-sheet" ? bsError : isError;

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
          {([["balance-sheet", "Balance Sheet"], ["income-statement", "Income Statement"]] as const).map(([t, label]) => (
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
        ) : null}
      </div>
    </div>
  );
}
