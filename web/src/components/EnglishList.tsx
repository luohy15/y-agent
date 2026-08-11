import { useMemo, useState } from "react";
import useSWR from "swr";
import { API, jsonFetcher as fetcher } from "../api";
import { ListEmpty, ListError, ListLoading } from "./ListStates";

export interface EnglishCorrection {
  correction_id: string;
  chat_id: string;
  message_id: string;
  message_at: string;
  message_at_unix: number;
  original_text: string;
  corrected_text: string;
  error_categories: string[];
  explanation: string;
  dismissed: boolean;
  created_at?: string | null;
}

interface Routine {
  routine_id: string;
  name: string;
  target_skill?: string | null;
  enabled: boolean;
  last_run_at?: string | null;
}

type StatusFilter = "active" | "dismissed" | "all";
type SubTab = "corrections" | "patterns";

interface EnglishListProps {
  isLoggedIn: boolean;
  selectedCorrectionId?: string | null;
  onSelectCorrection?: (correctionId: string) => void;
}

const STATUS_KEY = "englishListStatus";
const CATEGORY_KEY = "englishListCategory";
const CAT_COLORS = [
  "text-sol-yellow",
  "text-sol-cyan",
  "text-sol-orange",
  "text-sol-magenta",
  "text-sol-violet",
  "text-sol-green",
  "text-sol-blue",
];

function catColor(cat: string, index: number): string {
  // Stable-ish color from category name hash, fall back to index palette.
  let h = 0;
  for (let i = 0; i < cat.length; i++) h = (h * 31 + cat.charCodeAt(i)) | 0;
  return CAT_COLORS[Math.abs(h) % CAT_COLORS.length] || CAT_COLORS[index % CAT_COLORS.length];
}

function formatRelative(iso: string | undefined | null, unixMs?: number): string {
  const d = unixMs ? new Date(unixMs) : iso ? new Date(iso) : null;
  if (!d || isNaN(d.getTime())) return "—";
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfMsg = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dayDiff = Math.round((startOfToday.getTime() - startOfMsg.getTime()) / 86400000);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  if (dayDiff === 0) return `today ${hh}:${mm}`;
  if (dayDiff === 1) return "yesterday";
  if (dayDiff < 7) return d.toLocaleDateString([], { month: "short", day: "numeric" });
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function formatLastRun(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function weekBounds(now = new Date()) {
  // Local week starting Monday 00:00.
  const day = now.getDay(); // 0=Sun
  const mondayOffset = day === 0 ? -6 : 1 - day;
  const startThis = new Date(now.getFullYear(), now.getMonth(), now.getDate() + mondayOffset);
  const startLast = new Date(startThis);
  startLast.setDate(startLast.getDate() - 7);
  const endLast = startThis;
  return { startThis: startThis.getTime(), startLast: startLast.getTime(), endLast: endLast.getTime() };
}

export default function EnglishList({
  isLoggedIn,
  selectedCorrectionId,
  onSelectCorrection,
}: EnglishListProps) {
  const [status, setStatus] = useState<StatusFilter>(
    () => (localStorage.getItem(STATUS_KEY) as StatusFilter) || "active",
  );
  const [category, setCategory] = useState<string>(
    () => localStorage.getItem(CATEGORY_KEY) || "",
  );
  const [search, setSearch] = useState("");
  const [subTab, setSubTab] = useState<SubTab>("corrections");
  const [spinning, setSpinning] = useState(false);

  const listKey = isLoggedIn ? `${API}/api/english/list?limit=500` : null;
  const { data, isLoading, isValidating, error, mutate } = useSWR<EnglishCorrection[]>(
    listKey,
    fetcher,
    { revalidateOnFocus: false },
  );
  const { data: routines } = useSWR<Routine[]>(
    isLoggedIn ? `${API}/api/routine/list?limit=100` : null,
    fetcher,
    { revalidateOnFocus: false },
  );

  const engRoutine = useMemo(
    () => (routines || []).find((r) => r.target_skill === "english-correction") || null,
    [routines],
  );

  const rows = useMemo(() => (Array.isArray(data) ? data : []), [data]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const r of rows) {
      for (const c of r.error_categories || []) set.add(c);
    }
    return [...set].sort();
  }, [rows]);

  const activeCount = useMemo(() => rows.filter((r) => !r.dismissed).length, [rows]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter((r) => {
      if (status === "active" && r.dismissed) return false;
      if (status === "dismissed" && !r.dismissed) return false;
      if (category && !(r.error_categories || []).includes(category)) return false;
      if (q) {
        const hay = `${r.original_text} ${r.corrected_text} ${r.explanation}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [rows, status, category, search]);

  const patternStats = useMemo(() => {
    const active = rows.filter((r) => !r.dismissed);
    const counts = new Map<string, number>();
    for (const r of active) {
      for (const c of r.error_categories || []) {
        counts.set(c, (counts.get(c) || 0) + 1);
      }
    }
    const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]);
    const max = sorted[0]?.[1] || 1;
    const { startThis, startLast, endLast } = weekBounds();
    let thisWeek = 0;
    let lastWeek = 0;
    for (const r of active) {
      const t = r.message_at_unix || (r.message_at ? new Date(r.message_at).getTime() : 0);
      if (t >= startThis) thisWeek++;
      else if (t >= startLast && t < endLast) lastWeek++;
    }
    let deltaLabel = "—";
    if (lastWeek === 0 && thisWeek === 0) deltaLabel = "no data yet";
    else if (lastWeek === 0) deltaLabel = `↑ ${thisWeek} new this week`;
    else {
      const pct = Math.round(((thisWeek - lastWeek) / lastWeek) * 100);
      if (pct < 0) deltaLabel = `↓ ${Math.abs(pct)}% fewer flags`;
      else if (pct > 0) deltaLabel = `↑ ${pct}% more flags`;
      else deltaLabel = "flat vs last week";
    }
    return { sorted, max, thisWeek, lastWeek, deltaLabel, activeCount: active.length };
  }, [rows]);

  const setStatusPersist = (s: StatusFilter) => {
    setStatus(s);
    localStorage.setItem(STATUS_KEY, s);
  };
  const setCategoryPersist = (c: string) => {
    setCategory(c);
    if (c) localStorage.setItem(CATEGORY_KEY, c);
    else localStorage.removeItem(CATEGORY_KEY);
  };

  const pillClass = (active: boolean) =>
    `px-1.5 py-0.5 rounded text-[0.6rem] cursor-pointer ${
      active ? "bg-sol-blue text-sol-base03" : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"
    }`;

  const headerStatus = engRoutine
    ? engRoutine.enabled
      ? `${activeCount} active · last run ${formatLastRun(engRoutine.last_run_at)}`
      : `${activeCount} active · routine disabled`
    : `${activeCount} active · no routine`;

  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      <div className="p-2 border-b border-sol-base02 flex flex-col gap-1.5">
        <div className="flex gap-1.5">
          <div className="flex-1 flex items-center gap-1.5 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-sol-base01 shrink-0">
              <circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" />
            </svg>
            <input
              type="text"
              placeholder="Search corrections…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="flex-1 min-w-0 bg-transparent text-sol-base0 outline-none placeholder:text-sol-base01"
            />
          </div>
          <button
            onClick={() => {
              mutate();
              setSpinning(true);
              setTimeout(() => setSpinning(false), 600);
            }}
            className="px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded text-sol-base01 hover:text-sol-base0 hover:border-sol-base0 transition-colors cursor-pointer"
            title="Refresh"
          >
            <svg className={`w-3.5 h-3.5 ${spinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" />
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
            </svg>
          </button>
        </div>

        <div className="flex items-center gap-1 flex-wrap">
          {(["active", "dismissed", "all"] as StatusFilter[]).map((s) => (
            <button key={s} onClick={() => setStatusPersist(s)} className={pillClass(status === s)}>
              {s === "active" ? "Active" : s === "dismissed" ? "Dismissed" : "All"}
            </button>
          ))}
          <span className="ml-auto text-[0.6rem] text-sol-base01">{headerStatus}</span>
        </div>

        {categories.length > 0 && (
          <div className="flex gap-1 flex-wrap">
            <button onClick={() => setCategoryPersist("")} className={pillClass(!category)}>
              All cats
            </button>
            {categories.map((c) => (
              <button key={c} onClick={() => setCategoryPersist(c)} className={pillClass(category === c)}>
                {c}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex border-b border-sol-base02 text-[0.65rem]">
        <button
          onClick={() => setSubTab("corrections")}
          className={`flex-1 py-1.5 cursor-pointer ${
            subTab === "corrections"
              ? "text-sol-blue border-b-2 border-sol-blue font-medium"
              : "text-sol-base01 hover:text-sol-base0"
          }`}
        >
          Corrections
        </button>
        <button
          onClick={() => setSubTab("patterns")}
          className={`flex-1 py-1.5 cursor-pointer ${
            subTab === "patterns"
              ? "text-sol-blue border-b-2 border-sol-blue font-medium"
              : "text-sol-base01 hover:text-sol-base0"
          }`}
        >
          Patterns
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-1.5">
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic p-2">Sign in to view corrections</p>
        ) : isLoading || isValidating ? (
          <ListLoading />
        ) : error && !data ? (
          <ListError error={error} />
        ) : subTab === "patterns" ? (
          patternStats.activeCount === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 px-4 py-8 text-center">
              <p className="text-sol-base01 text-[0.7rem]">No active corrections yet</p>
              <p className="text-sol-base01/80 text-[0.6rem] leading-relaxed">
                Patterns are derived from non-dismissed corrections.
              </p>
            </div>
          ) : (
            <div className="p-1.5 space-y-3">
              <div>
                <div className="text-[0.7rem] text-sol-base1 font-medium">Recurring patterns</div>
                <div className="text-[0.55rem] text-sol-base01 mt-0.5">
                  {patternStats.activeCount} active corrections
                </div>
              </div>
              {patternStats.sorted.map(([cat, count], i) => (
                <div key={cat}>
                  <div className="flex justify-between text-[0.65rem] mb-1">
                    <span className={catColor(cat, i)}>{cat}</span>
                    <span className="text-sol-base01 font-mono">{count}</span>
                  </div>
                  <div className="h-1.5 rounded bg-sol-base02 overflow-hidden">
                    <i
                      className="block h-full bg-sol-blue rounded"
                      style={{ width: `${Math.max(8, (count / patternStats.max) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
              <div className="pt-2 border-t border-sol-base02">
                <div className="text-[0.6rem] uppercase tracking-wider text-sol-base01 mb-2">
                  Progress (WoW)
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="rounded bg-sol-base02 px-2 py-1.5">
                    <div className="text-[0.55rem] text-sol-base01">This week</div>
                    <div className="text-sm text-sol-base1 font-mono">{patternStats.thisWeek}</div>
                  </div>
                  <div className="rounded bg-sol-base02 px-2 py-1.5">
                    <div className="text-[0.55rem] text-sol-base01">Last week</div>
                    <div className="text-sm text-sol-base1 font-mono">{patternStats.lastWeek}</div>
                  </div>
                  <div className="rounded bg-sol-base02 px-2 py-1.5 col-span-2">
                    <div className="text-[0.55rem] text-sol-base01">Delta</div>
                    <div
                      className={`text-sm font-mono ${
                        patternStats.deltaLabel.startsWith("↓")
                          ? "text-sol-green"
                          : patternStats.deltaLabel.startsWith("↑")
                            ? "text-sol-orange"
                            : "text-sol-base1"
                      }`}
                    >
                      {patternStats.deltaLabel}
                    </div>
                  </div>
                </div>
                <p className="text-[0.55rem] text-sol-base01 mt-2 leading-relaxed">
                  Counts exclude dismissed rows. No rollup table in v1; computed from list data.
                </p>
              </div>
            </div>
          )
        ) : filtered.length === 0 ? (
          rows.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-sol-base01">
                <path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
              </svg>
              <p className="text-sol-base01 text-[0.7rem]">No corrections yet</p>
              <p className="text-sol-base01/80 text-[0.6rem] leading-relaxed">
                Hourly routine scans your English chat messages. First results appear after the next run.
              </p>
            </div>
          ) : (
            <ListEmpty label="corrections" />
          )
        ) : (
          <div className="space-y-0.5">
            {filtered.map((r) => {
              const isSelected = selectedCorrectionId === r.correction_id;
              return (
                <button
                  key={r.correction_id}
                  onClick={() => onSelectCorrection?.(r.correction_id)}
                  className={`w-full text-left px-2 py-1.5 rounded cursor-pointer ${
                    isSelected
                      ? "bg-sol-base02 border border-sol-base01/40"
                      : "hover:bg-sol-base02/50 border border-transparent"
                  }`}
                >
                  <div className="flex items-start gap-1.5">
                    <span
                      className={`mt-0.5 w-1.5 h-1.5 rounded-full shrink-0 ${
                        r.dismissed ? "bg-sol-base01" : "bg-sol-blue"
                      }`}
                      title={r.dismissed ? "dismissed" : "active"}
                    />
                    <div className="min-w-0 flex-1">
                      <div
                        className={`text-[0.7rem] truncate ${
                          isSelected ? "text-sol-base1" : "text-sol-base0"
                        }`}
                        title={r.original_text}
                      >
                        {r.original_text.replace(/\s+/g, " ")}
                      </div>
                      <div className="flex items-center gap-1 mt-0.5 flex-wrap">
                        {(r.error_categories || []).map((c, i) => (
                          <span
                            key={c}
                            className={`px-1 rounded bg-sol-base03 ${catColor(c, i)} text-[0.55rem]`}
                          >
                            {c}
                          </span>
                        ))}
                        <span className="ml-auto text-[0.55rem] text-sol-base01 font-mono">
                          {formatRelative(r.message_at, r.message_at_unix)}
                        </span>
                      </div>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="px-2 py-1.5 border-t border-sol-base02 text-[0.55rem] text-sol-base01 leading-relaxed shrink-0">
        Auto-scan runs hourly via routine{" "}
        <span className="text-sol-cyan font-mono">english-correction</span>. Toggle in Routines · no
        settings here.
      </div>
    </div>
  );
}
