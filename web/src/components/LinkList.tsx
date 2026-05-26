import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import useSWR from "swr";
import { API, authFetch, jsonFetcher as fetcher } from "../api";
import { ListEmpty, ListError, ListLoading } from "./ListStates";
import { ALL_RSS_FEEDS_ID } from "./RssFeedList";

interface Link {
  activity_id: string;
  link_id: string;
  url: string;
  base_url: string;
  title?: string;
  timestamp?: number;
  published_at?: number | null;
  download_status?: string | null;
  content_key?: string | null;
  summary_content_key?: string | null;
  source?: string | null;
  source_feed_id?: string | null;
}

function linkTime(link: Link): number | undefined {
  return link.published_at ?? link.timestamp;
}

type Chip = "today" | "7d" | "30d";
type FilterMode = "chip" | "range" | "all";

interface FilterState {
  mode: FilterMode;
  chip?: Chip;
  from?: string;
  to?: string;
}

const DEFAULT_FILTER: FilterState = { mode: "chip", chip: "7d" };

function ymd(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function shiftDays(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return ymd(d);
}

function filterToParams(state: FilterState): { on?: string; from?: string; to?: string } {
  if (state.mode === "all") return {};
  if (state.mode === "chip") {
    if (state.chip === "today") return { on: ymd(new Date()) };
    if (state.chip === "7d") return { from: shiftDays(6), to: shiftDays(0) };
    if (state.chip === "30d") return { from: shiftDays(29), to: shiftDays(0) };
    return {};
  }
  if (state.from && state.to && state.from === state.to) return { on: state.from };
  const out: { on?: string; from?: string; to?: string } = {};
  if (state.from) out.from = state.from;
  if (state.to) out.to = state.to;
  return out;
}

function loadFilter(): FilterState {
  try {
    const raw = localStorage.getItem("linkListFilter.v2");
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed && (parsed.mode === "chip" || parsed.mode === "range" || parsed.mode === "all")) {
        return parsed as FilterState;
      }
    }
  } catch {
    // fall through to migration / default
  }
  const old = localStorage.getItem("linkListDateRange");
  if (old) {
    localStorage.removeItem("linkListDateRange");
    if (old === "all") return { mode: "all" };
    if (old === "today" || old === "7d" || old === "30d") return { mode: "chip", chip: old };
  }
  return DEFAULT_FILTER;
}

function getDomain(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function formatTime(ts: number): string {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function formatDayHeader(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  const days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  return `${d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })} - ${days[d.getDay()]}`;
}

function groupByDay(links: Link[]): [string, Link[]][] {
  const groups = new Map<string, Link[]>();
  for (const link of links) {
    const ts = linkTime(link);
    if (!ts) continue;
    const d = new Date(ts);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(link);
  }
  const entries = [...groups.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  for (const [, links] of entries) {
    links.sort((a, b) => (linkTime(b) || 0) - (linkTime(a) || 0));
  }
  return entries;
}

async function downloadLinks(urls: string[]): Promise<any> {
  const res = await authFetch(`${API}/api/link/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ urls }),
  });
  return res.json();
}

function DownloadButton({ link, onStatusChange }: { link: Link; onStatusChange: (url: string, status: string) => void }) {
  const status = link.download_status;
  const isLoading = status === "pending" || status === "downloading";

  const handleClick = async () => {
    if (isLoading) return;
    onStatusChange(link.url, "pending");
    try {
      await downloadLinks([link.url]);
    } catch {
      onStatusChange(link.url, "failed");
    }
  };

  if (isLoading) {
    return (
      <span className="shrink-0 w-4 h-4 flex items-center justify-center text-sol-yellow" title="Downloading...">
        <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" strokeLinecap="round"/></svg>
      </span>
    );
  }
  if (status === "done") {
    return (
      <button onClick={handleClick} className="shrink-0 w-4 h-4 flex items-center justify-center text-sol-green hover:text-sol-blue cursor-pointer" title="Re-download">
        <svg className="w-3 h-3" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/></svg>
      </button>
    );
  }
  if (status === "failed") {
    return (
      <button onClick={handleClick} className="shrink-0 w-4 h-4 flex items-center justify-center text-sol-red hover:text-sol-orange cursor-pointer" title="Failed - click to retry">
        <svg className="w-3 h-3" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clipRule="evenodd"/></svg>
      </button>
    );
  }
  return (
    <button onClick={handleClick} className="shrink-0 w-4 h-4 flex items-center justify-center text-sol-base01 opacity-0 group-hover:opacity-100 hover:text-sol-blue cursor-pointer" title="Download content">
      <svg className="w-3 h-3" viewBox="0 0 20 20" fill="currentColor"><path d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z"/></svg>
    </button>
  );
}

async function generateTldr(linkId: string): Promise<any> {
  const res = await authFetch(`${API}/api/link/tldr`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ link_id: linkId }),
  });
  if (!res.ok) throw new Error("Failed to generate TLDR");
  return res.json();
}

function TldrButton({ link, onGenerated }: { link: Link; onGenerated: (linkId: string, key: string) => void }) {
  const [loading, setLoading] = useState(false);
  const handleGenerate = async () => {
    if (loading) return;
    setLoading(true);
    try {
      const data = await generateTldr(link.link_id);
      if (data.summary_content_key) onGenerated(link.link_id, data.summary_content_key);
    } finally {
      setLoading(false);
    }
  };

  if (link.summary_content_key) {
    return (
      <span className="shrink-0 px-1 rounded text-[0.55rem] font-medium bg-sol-blue/20 text-sol-blue" title={link.summary_content_key}>
        TLDR
      </span>
    );
  }
  return (
    <button
      onClick={handleGenerate}
      disabled={loading}
      className="shrink-0 px-1 rounded text-[0.55rem] font-medium bg-sol-base02 text-sol-base01 hover:text-sol-base0 cursor-pointer disabled:opacity-50"
      title="Generate TLDR"
    >
      {loading ? "..." : "+TLDR"}
    </button>
  );
}

function ExternalLinkButton({ link }: { link: Link }) {
  return (
    <button
      onClick={() => window.open(link.url, "_blank", "noopener,noreferrer")}
      className="shrink-0 w-4 h-4 flex items-center justify-center text-sol-base01 opacity-0 group-hover:opacity-100 hover:text-sol-cyan cursor-pointer"
      title={`Open original page: ${link.url}`}
      aria-label="Open original page in new tab"
    >
      <svg className="w-3 h-3" viewBox="0 0 20 20" fill="currentColor">
        <path d="M11 3a1 1 0 100 2h2.586l-6.293 6.293a1 1 0 101.414 1.414L15 6.414V9a1 1 0 102 0V4a1 1 0 00-1-1h-5z"/>
        <path d="M5 5a2 2 0 00-2 2v8a2 2 0 002 2h8a2 2 0 002-2v-3a1 1 0 10-2 0v3H5V7h3a1 1 0 000-2H5z"/>
      </svg>
    </button>
  );
}

const LIMIT = 50;

interface LinkListProps {
  isLoggedIn: boolean;
  onPreview: (link: Link) => void;
  todoId?: string | null;
  feedId?: string | null;
  hideFilters?: boolean;
  refreshKey?: number;
}

export default function LinkList({ isLoggedIn, onPreview, todoId, feedId, hideFilters, refreshKey }: LinkListProps) {
  const [filter, setFilter] = useState<FilterState>(loadFilter);
  const [rangeExpanded, setRangeExpanded] = useState<boolean>(filter.mode === "range");
  const [downloadedOnly, setDownloadedOnly] = useState(() => localStorage.getItem("linkListDownloaded") === "true");
  const [query, setQuery] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [offset, setOffset] = useState(0);
  const [allLinks, setAllLinks] = useState<Link[]>([]);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [spinning, setSpinning] = useState(false);
  useEffect(() => { localStorage.setItem("linkListFilter.v2", JSON.stringify(filter)); }, [filter]);
  useEffect(() => { localStorage.setItem("linkListDownloaded", String(downloadedOnly)); }, [downloadedOnly]);
  useEffect(() => { setOffset(0); setAllLinks([]); setLoadedOnce(false); }, [todoId, feedId, downloadedOnly]);

  const timeParams = filterToParams(filter);
  const params = new URLSearchParams();
  if (timeParams.on) params.set("on", timeParams.on);
  if (timeParams.from) params.set("from", timeParams.from);
  if (timeParams.to) params.set("to", timeParams.to);
  if (query) params.set("query", query);
  if (todoId) params.set("todo_id", todoId);
  if (feedId === ALL_RSS_FEEDS_ID) {
    params.set("source", "rss");
  } else if (feedId) {
    params.set("source_feed_id", feedId);
  }
  if (downloadedOnly) params.set("downloaded", "true");
  params.set("limit", String(LIMIT));
  params.set("offset", String(offset));

  const swrKey = isLoggedIn ? `${API}/api/link/list?${params.toString()}` : null;

  const { data, isLoading, isValidating, error, mutate } = useSWR<Link[]>(swrKey, fetcher, {
    onSuccess: (newData) => {
      if (offset === 0) {
        setAllLinks(newData);
      } else {
        setAllLinks((prev) => [...prev, ...newData]);
      }
      setLoadedOnce(true);
    },
    revalidateOnFocus: false,
  });

  const hasMore = data && data.length === LIMIT;

  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    if (offset === 0) {
      mutate();
      return;
    }
    setOffset(0);
    setAllLinks([]);
    setLoadedOnce(false);
  }, [refreshKey, offset, mutate]);

  const handleSearch = useCallback(() => {
    setQuery(searchInput);
    setOffset(0);
    setAllLinks([]);
    setLoadedOnce(false);
  }, [searchInput]);

  const resetPaging = useCallback(() => {
    setOffset(0);
    setAllLinks([]);
    setLoadedOnce(false);
  }, []);

  const handleChipClick = useCallback((c: Chip | "all") => {
    setFilter(c === "all" ? { mode: "all" } : { mode: "chip", chip: c });
    resetPaging();
  }, [resetPaging]);

  const handleRangeInput = useCallback((side: "from" | "to", value: string) => {
    setFilter((prev) => {
      const next: FilterState = {
        mode: "range",
        from: prev.mode === "range" ? prev.from : undefined,
        to: prev.mode === "range" ? prev.to : undefined,
      };
      next[side] = value || undefined;
      return next;
    });
    resetPaging();
  }, [resetPaging]);

  const handleLoadMore = useCallback(() => {
    setOffset((prev) => prev + LIMIT);
  }, []);

  const handleDownloadStatusChange = useCallback((url: string, status: string) => {
    setAllLinks((prev) =>
      prev.map((l) => l.url === url ? { ...l, download_status: status } : l)
    );
  }, []);

  const handleTldrGenerated = useCallback((linkId: string, key: string) => {
    setAllLinks((prev) => prev.map((l) => l.link_id === linkId ? { ...l, summary_content_key: key } : l));
  }, []);

  const grouped = useMemo(() => groupByDay(allLinks), [allLinks]);
  const showRangeRow = rangeExpanded || filter.mode === "range";

  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      {!hideFilters && (
        <div className="p-2 border-b border-sol-base02 flex flex-col gap-1.5">
          <div className="flex gap-1.5">
            <input
              type="text"
              placeholder="Search links..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
              className="flex-1 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
            />
            <button
              onClick={() => { mutate(); setSpinning(true); setTimeout(() => setSpinning(false), 600); }}
              className="px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base01 hover:text-sol-base0 hover:border-sol-base0 transition-colors cursor-pointer"
              title="Refresh"
            >
              <svg className={`w-3.5 h-3.5 ${spinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
            </button>
          </div>
          <div className="flex gap-1 items-center">
            {(["today", "7d", "30d", "all"] as const).map((c) => {
              const active = c === "all"
                ? filter.mode === "all"
                : filter.mode === "chip" && filter.chip === c;
              return (
                <button
                  key={c}
                  onClick={() => handleChipClick(c)}
                  className={`px-1.5 py-0.5 rounded text-[0.6rem] cursor-pointer ${
                    active
                      ? "bg-sol-blue text-sol-base03"
                      : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"
                  }`}
                >
                  {c === "today" ? "Today" : c === "7d" ? "7d" : c === "30d" ? "30d" : "All"}
                </button>
              );
            })}
            <button
              onClick={() => setRangeExpanded((v) => !v)}
              className={`px-1.5 py-0.5 rounded text-[0.6rem] cursor-pointer ${
                filter.mode === "range"
                  ? "bg-sol-blue text-sol-base03"
                  : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"
              }`}
              title="Custom date range"
              aria-label="Toggle custom date range"
              aria-expanded={showRangeRow}
            >
              {showRangeRow ? "▾" : "▸"}
            </button>
            <button
              onClick={() => setDownloadedOnly((v) => !v)}
              className={`px-1.5 py-0.5 rounded text-[0.6rem] cursor-pointer ml-auto ${
                downloadedOnly
                  ? "bg-sol-green text-sol-base03"
                  : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"
              }`}
            >
              Downloaded
            </button>
          </div>
          {showRangeRow && (
            <div className="flex gap-1 items-center text-[0.6rem]">
              <input
                type="date"
                value={filter.mode === "range" ? filter.from ?? "" : ""}
                onChange={(e) => handleRangeInput("from", e.target.value)}
                className="flex-1 px-1.5 py-0.5 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none focus:border-sol-blue"
                aria-label="From date"
              />
              <span className="text-sol-base01">–</span>
              <input
                type="date"
                value={filter.mode === "range" ? filter.to ?? "" : ""}
                onChange={(e) => handleRangeInput("to", e.target.value)}
                className="flex-1 px-1.5 py-0.5 bg-sol-base02 border border-sol-base01 rounded text-sol-base0 outline-none focus:border-sol-blue"
                aria-label="To date"
              />
            </div>
          )}
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-1.5">
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic p-2">Sign in to view links</p>
        ) : isLoading || isValidating ? (
          <ListLoading />
        ) : error && grouped.length === 0 ? (
          <ListError error={error} />
        ) : grouped.length === 0 ? (
          <ListEmpty label="links" />
        ) : (
          <>
            {grouped.map(([day, links]) => (
              <div key={day} className="mb-2">
                <div className="text-sol-base01 text-[0.6rem] font-medium mb-1 px-1 sticky top-0 bg-sol-base03 py-0.5 z-[5] border-b border-sol-base02">
                  {formatDayHeader(day)}
                </div>
                <div className="space-y-0">
                  {links.map((link) => (
                    <div key={link.activity_id} className="flex items-center gap-1.5 py-0.5 px-1 rounded hover:bg-sol-base02/50 group">
                      <span className="text-sol-base01 text-[0.6rem] shrink-0 w-8 text-right">
                        {linkTime(link) ? formatTime(linkTime(link)!) : ""}
                      </span>
                      <img
                        src={`https://www.google.com/s2/favicons?domain=${getDomain(link.base_url)}&sz=16`}
                        alt=""
                        className="w-3.5 h-3.5 shrink-0"
                        loading="lazy"
                      />
                      <button
                        onClick={() => onPreview(link)}
                        className="text-sol-base0 hover:text-sol-blue truncate text-[0.7rem] min-w-0 flex-1 text-left cursor-pointer bg-transparent border-0 p-0"
                        title={link.url}
                        aria-label={`Open internal view for ${link.title || link.url}`}
                      >
                        {link.title || getDomain(link.base_url)}
                      </button>
                      {link.source === "rss" && (
                        <span className="shrink-0 px-1 rounded text-[0.55rem] font-medium bg-sol-orange/20 text-sol-orange" title={link.source_feed_id ? `RSS: ${link.source_feed_id}` : "From RSS feed"}>
                          RSS
                        </span>
                      )}
                      <TldrButton link={link} onGenerated={handleTldrGenerated} />
                      <ExternalLinkButton link={link} />
                      <DownloadButton link={link} onStatusChange={handleDownloadStatusChange} />
                    </div>
                  ))}
                </div>
              </div>
            ))}
            {hasMore && (
              <button
                onClick={handleLoadMore}
                disabled={isLoading}
                className="w-full py-1.5 text-center text-[0.6rem] rounded bg-sol-base02 text-sol-base0 hover:text-sol-base1 cursor-pointer disabled:opacity-50 mb-2"
              >
                {isLoading ? "Loading..." : "Load more"}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export type { Link };
