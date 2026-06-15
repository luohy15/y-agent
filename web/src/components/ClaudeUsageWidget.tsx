import useSWR from "swr";
import { API, jsonFetcher as fetcher } from "../api";

// Past this age the cached scrape is treated as stale: the widget dims and the
// tooltip still shows the last-known "as of HH:MM". Threshold is generous so a
// normal routine cadence (hourly-ish) never falsely dims a fresh value.
const STALE_MS = 2 * 60 * 60 * 1000;

interface Window {
  percent?: number | null;
  reset?: string | null;
}

interface UsageBlob {
  cached?: boolean;
  parse_ok?: boolean;
  scraped_at?: string;
  data?: {
    session?: Window | null;
    week_all?: Window | null;
    week_sonnet?: Window | null;
  };
}

function barColor(percent: number): string {
  if (percent >= 90) return "bg-sol-red";
  if (percent >= 75) return "bg-sol-orange";
  if (percent >= 50) return "bg-sol-yellow";
  return "bg-sol-green";
}

function asOf(scrapedAt?: string): string | null {
  if (!scrapedAt) return null;
  const d = new Date(scrapedAt);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function UsageBar({
  label,
  win,
  compact,
}: {
  label: string;
  win?: Window | null;
  compact?: boolean;
}) {
  const percent = typeof win?.percent === "number" ? win.percent : null;
  const reset = win?.reset || null;
  const tip = [label, percent !== null ? `${percent}%` : "—", reset ? `resets ${reset}` : null]
    .filter(Boolean)
    .join(" · ");
  return (
    <div className="flex items-center gap-2" title={tip}>
      <span className={`shrink-0 text-sol-base01 ${compact ? "w-12 text-[10px]" : "w-14 text-[11px]"}`}>
        {label}
      </span>
      <div className={`flex-1 rounded-full bg-sol-base02 overflow-hidden ${compact ? "h-1" : "h-1.5"}`}>
        <div
          className={`h-full rounded-full ${percent !== null ? barColor(percent) : "bg-sol-base01"}`}
          style={{ width: `${percent !== null ? Math.min(100, Math.max(0, percent)) : 0}%` }}
        />
      </div>
      <span className={`shrink-0 tabular-nums text-right text-sol-base1 ${compact ? "w-7 text-[10px]" : "w-8 text-[11px]"}`}>
        {percent !== null ? `${percent}%` : "—"}
      </span>
    </div>
  );
}

export default function ClaudeUsageWidget({ isLoggedIn }: { isLoggedIn: boolean }) {
  const key = isLoggedIn ? `${API}/api/claude/usage` : null;
  const { data } = useSWR<UsageBlob>(key, fetcher, {
    refreshInterval: 60000,
    revalidateOnFocus: false,
  });

  if (!isLoggedIn) return null;

  const hasData = data && data.cached !== false && data.data;
  const stale =
    hasData && data?.scraped_at
      ? Date.now() - new Date(data.scraped_at).getTime() > STALE_MS
      : false;
  const ts = asOf(data?.scraped_at);

  return (
    <div className="shrink-0 border-t border-sol-base02 px-3 py-2 bg-sol-base03">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-wide text-sol-base01">Claude usage</span>
        {hasData && ts && (
          <span className={`text-[10px] ${stale ? "text-sol-orange" : "text-sol-base01"}`} title={`Cached scrape from ${data?.scraped_at}`}>
            {stale ? "stale · " : "as of "}
            {ts}
          </span>
        )}
      </div>
      {!hasData ? (
        <div className="text-[11px] text-sol-base01">no data</div>
      ) : (
        <div className={`space-y-1 ${stale ? "opacity-50" : ""}`}>
          <UsageBar label="session" win={data?.data?.session} />
          <UsageBar label="week" win={data?.data?.week_all} />
          <UsageBar label="sonnet" win={data?.data?.week_sonnet} compact />
        </div>
      )}
    </div>
  );
}
