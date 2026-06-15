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

const MONTHS: Record<string, number | undefined> = {
  jan: 0,
  january: 0,
  feb: 1,
  february: 1,
  mar: 2,
  march: 2,
  apr: 3,
  april: 3,
  may: 4,
  jun: 5,
  june: 5,
  jul: 6,
  july: 6,
  aug: 7,
  august: 7,
  sep: 8,
  sept: 8,
  september: 8,
  oct: 9,
  october: 9,
  nov: 10,
  november: 10,
  dec: 11,
  december: 11,
};

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

function parseTimePart(value: string): { hour: number; minute: number } | null {
  const match = value.trim().match(/^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$/i);
  if (!match) return null;

  const rawHour = Number(match[1]);
  const minute = match[2] ? Number(match[2]) : 0;
  if (rawHour < 1 || rawHour > 12 || minute < 0 || minute > 59) return null;

  const meridiem = match[3].toLowerCase();
  let hour = rawHour % 12;
  if (meridiem === "pm") hour += 12;
  return { hour, minute };
}

export function parseClaudeResetAt(reset: string, now = new Date()): Date | null {
  const usesUtc = /\bUTC\b/i.test(reset);
  const cleaned = reset.replace(/\s*\([^)]*\)\s*$/, "").trim();
  const dateMatch = cleaned.match(/^([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(.+)$/);

  const month = dateMatch ? MONTHS[dateMatch[1].toLowerCase()] : null;
  const day = dateMatch ? Number(dateMatch[2]) : null;
  const timePart = dateMatch ? dateMatch[3] : cleaned;
  const parsedTime = parseTimePart(timePart);
  if (!parsedTime) return null;
  if (dateMatch && month === undefined) return null;

  const year = usesUtc ? now.getUTCFullYear() : now.getFullYear();
  const makeDate = (targetYear: number, targetMonth: number, targetDay: number) =>
    usesUtc
      ? new Date(Date.UTC(targetYear, targetMonth, targetDay, parsedTime.hour, parsedTime.minute))
      : new Date(targetYear, targetMonth, targetDay, parsedTime.hour, parsedTime.minute);

  if (month !== null && day !== null) {
    if (!Number.isInteger(day) || day < 1 || day > 31) return null;
    let target = makeDate(year, month, day);
    if (target.getTime() < now.getTime()) {
      target = makeDate(year + 1, month, day);
    }
    return target;
  }

  const todayMonth = usesUtc ? now.getUTCMonth() : now.getMonth();
  const todayDay = usesUtc ? now.getUTCDate() : now.getDate();
  let target = makeDate(year, todayMonth, todayDay);
  if (target.getTime() < now.getTime()) {
    target = new Date(target.getTime() + 24 * 60 * 60 * 1000);
  }
  return target;
}

export function formatResetCountdown(reset: string | null | undefined, now = new Date()): string | null {
  if (!reset) return null;

  const target = parseClaudeResetAt(reset, now);
  if (!target) return null;

  const minutes = Math.max(0, Math.ceil((target.getTime() - now.getTime()) / 60000));
  if (minutes === 0) return "now";
  if (minutes < 60) return `in ${minutes}m`;

  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (hours < 24) {
    return `in ${hours}h${remainingMinutes ? ` ${remainingMinutes}m` : ""}`;
  }

  const days = Math.floor(hours / 24);
  const remainingHours = hours % 24;
  return `in ${days}d${remainingHours ? ` ${remainingHours}h` : ""}`;
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
  const resetCountdown = formatResetCountdown(reset);
  const resetText = reset ? `resets ${resetCountdown || reset}` : null;
  const tip = [label, percent !== null ? `${percent}%` : "—", resetText, reset ? `at ${reset}` : null]
    .filter(Boolean)
    .join(" · ");
  return (
    <div
      className={`grid items-center gap-x-2 gap-y-0.5 ${compact ? "grid-cols-[3rem_minmax(0,1fr)_1.75rem]" : "grid-cols-[3.5rem_minmax(0,1fr)_2rem]"}`}
      title={tip}
    >
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
      {resetText && (
        <span className="col-start-2 col-span-2 min-w-0 truncate text-[10px] leading-none text-sol-base01">
          {resetText}
        </span>
      )}
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
