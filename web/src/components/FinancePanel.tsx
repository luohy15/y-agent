import useSWR from "swr";
import { API, jsonFetcher as fetcher } from "../api";
import { ListEmpty, ListError, ListLoading } from "./ListStates";

interface QuickStats {
  assets_usd: number | null;
  liabilities_usd: number | null;
  net_worth_usd: number | null;
  risky: {
    total_base: number | null;
    risky_base: number | null;
    risky_pct: number | null;
    base_currency: string;
  };
  fire: {
    progress_pct: number | null;
    target_usd: number | null;
    gap_usd: number | null;
    projected_date: string | null;
    projected_months_to_target: number | null;
  };
}

interface LargeTransaction {
  date: string;
  amount_usd: number;
  payee: string;
  narration: string;
  symbol: string;
}

// Both controller routes return the standard finance envelope; jsonFetcher does
// not unwrap, so read `.data`.
interface Envelope<T> {
  data: T;
  synced_at?: string;
  source?: string;
}

function formatAmount(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return "—";
  return (amount === 0 ? 0 : amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatPct(value: number | null | undefined, scale = 1): string {
  if (value === null || value === undefined) return "—";
  return `${(value * scale).toFixed(1)}%`;
}

function StatRow({ label, value, subtext }: { label: string; value: string; subtext?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2 py-0.5 px-1">
      <span className="text-sol-base01 shrink-0">{label}</span>
      <span className="text-right">
        <span className="text-sol-base1 tabular-nums">{value}</span>
        {subtext && <span className="block text-[0.6rem] text-sol-base01 tabular-nums">{subtext}</span>}
      </span>
    </div>
  );
}

interface FinancePanelProps {
  isLoggedIn: boolean;
}

export default function FinancePanel({ isLoggedIn }: FinancePanelProps) {
  const { data: statsResp, isLoading: statsLoading, error: statsError } = useSWR<Envelope<QuickStats>>(
    isLoggedIn ? `${API}/api/finance/quick-stats` : null,
    fetcher,
  );
  const { data: txnsResp, isLoading: txnsLoading, error: txnsError } = useSWR<Envelope<LargeTransaction[]>>(
    isLoggedIn ? `${API}/api/finance/large-transactions` : null,
    fetcher,
  );
  const stats = statsResp?.data;
  const txns = txnsResp?.data;

  if (!isLoggedIn) {
    return <p className="text-sol-base01 italic p-2 text-xs">Sign in to view finance</p>;
  }

  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      <div className="flex-1 overflow-y-auto p-1.5 space-y-3">
        {/* Quick numbers */}
        <div>
          <div className="text-[0.6rem] font-medium mb-1 px-1 text-sol-base01 uppercase tracking-wide">
            Quick numbers
          </div>
          {statsLoading ? (
            <ListLoading />
          ) : statsError && !stats ? (
            <ListError error={statsError} />
          ) : !stats ? (
            <ListEmpty label="stats" />
          ) : (
            <div className="space-y-0">
              <StatRow label="Assets" value={formatAmount(stats.assets_usd)} />
              <StatRow label="Liabilities" value={formatAmount(stats.liabilities_usd)} />
              <StatRow label="Net Worth" value={formatAmount(stats.net_worth_usd)} />
              <StatRow
                label="Risky Alloc"
                value={formatPct(stats.risky.risky_pct, 100)}
                subtext={
                  stats.risky.risky_base !== null && stats.risky.total_base !== null
                    ? `${formatAmount(stats.risky.risky_base)} / ${formatAmount(stats.risky.total_base)}`
                    : undefined
                }
              />
              <StatRow
                label="FIRE"
                value={formatPct(stats.fire.progress_pct)}
                subtext={stats.fire.projected_date ? `~${stats.fire.projected_date}` : undefined}
              />
            </div>
          )}
        </div>

        {/* Large transactions */}
        <div>
          <div className="text-[0.6rem] font-medium mb-1 px-1 text-sol-base01 uppercase tracking-wide">
            Large transactions
          </div>
          {txnsLoading ? (
            <ListLoading />
          ) : txnsError && !txns ? (
            <ListError error={txnsError} />
          ) : !txns || txns.length === 0 ? (
            <ListEmpty label="transactions" />
          ) : (
            <div className="space-y-0">
              {txns.map((txn, i) => {
                const label = [txn.payee, txn.narration].filter(Boolean).join(" · ");
                return (
                  <div
                    key={`${txn.date}-${i}`}
                    className="flex items-baseline gap-1.5 py-0.5 px-1 text-[0.7rem]"
                    title={label || txn.symbol}
                  >
                    <span className="text-sol-base01 tabular-nums shrink-0 w-14">{txn.date}</span>
                    <span className="text-sol-base1 tabular-nums shrink-0 text-right w-16">
                      {formatAmount(txn.amount_usd)}
                    </span>
                    <span className="text-sol-base0 truncate flex-1">{label || txn.symbol}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
