import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import useSWR from "swr";
import { API, authFetch, clearToken } from "../api";

interface Link {
  activity_id: string;
  link_id: string;
  url: string;
  base_url: string;
  title?: string;
  timestamp?: number;
  download_status?: string | null;
  content_key?: string | null;
}

const fetcher = async (url: string) => {
  const res = await authFetch(url);
  if (res.status === 401) {
    clearToken();
    throw new Error("Unauthorized");
  }
  return res.json();
};

type DateRange = "today" | "7d" | "30d" | "all";

function getRange(range: DateRange): { start?: number; end?: number } {
  if (range === "all") return {};
  const now = new Date();
  const dayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const dayEnd = dayStart + 86400000;
  switch (range) {
    case "today": return { start: dayStart, end: dayEnd };
    case "7d": return { start: dayStart - 6 * 86400000, end: dayEnd };
    case "30d": return { start: dayStart - 29 * 86400000, end: dayEnd };
  }
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
    if (!link.timestamp) continue;
    const d = new Date(link.timestamp);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(link);
  }
  const entries = [...groups.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  for (const [, links] of entries) {
    links.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
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

function PreviewButton({ link, onPreview }: { link: Link; onPreview: (link: Link) => void }) {
  if (link.download_status !== "done") return null;
  return (
    <button
      onClick={() => onPreview(link)}
      className="shrink-0 w-4 h-4 flex items-center justify-center text-sol-base01 opacity-0 group-hover:opacity-100 hover:text-sol-cyan cursor-pointer"
      title="Preview content"
    >
      <svg className="w-3 h-3" viewBox="0 0 20 20" fill="currentColor">
        <path d="M10 12a2 2 0 100-4 2 2 0 000 4z"/>
        <path fillRule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clipRule="evenodd"/>
      </svg>
    </button>
  );
}

const LIMIT = 50;

interface LinkListProps {
  isLoggedIn: boolean;
  onPreview: (link: Link) => void;
  todoId?: string | null;
}

export default function LinkList({ isLoggedIn, onPreview, todoId }: LinkListProps) {
  const [range, setRange] = useState<DateRange>(() => {
    const saved = localStorage.getItem("linkListDateRange");
    return (saved === "today" || saved === "7d" || saved === "30d" || saved === "all") ? saved : "7d";
  });
  const [query, setQuery] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [offset, setOffset] = useState(0);
  const [allLinks, setAllLinks] = useState<Link[]>([]);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [spinning, setSpinning] = useState(false);
  useEffect(() => { localStorage.setItem("linkListDateRange", range); }, [range]);
  useEffect(() => { setOffset(0); setAllLinks([]); setLoadedOnce(false); }, [todoId]);

  const { start, end } = getRange(range);
  const params = new URLSearchParams();
  if (start !== undefined) params.set("start", String(start));
  if (end !== undefined) params.set("end", String(end));
  if (query) params.set("query", query);
  if (todoId) params.set("todo_id", todoId);
  params.set("limit", String(LIMIT));
  params.set("offset", String(offset));

  const swrKey = isLoggedIn ? `${API}/api/link/list?${params.toString()}` : null;

  const { data, isLoading, error, mutate } = useSWR<Link[]>(swrKey, fetcher, {
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

  const handleSearch = useCallback(() => {
    setQuery(searchInput);
    setOffset(0);
    setAllLinks([]);
    setLoadedOnce(false);
  }, [searchInput]);

  const handleRangeChange = useCallback((r: DateRange) => {
    setRange(r);
    setOffset(0);
    setAllLinks([]);
    setLoadedOnce(false);
  }, []);

  const handleLoadMore = useCallback(() => {
    setOffset((prev) => prev + LIMIT);
  }, []);

  const handleDownloadStatusChange = useCallback((url: string, status: string) => {
    setAllLinks((prev) =>
      prev.map((l) => l.url === url ? { ...l, download_status: status } : l)
    );
  }, []);

  const grouped = useMemo(() => groupByDay(allLinks), [allLinks]);

  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
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
        <div className="flex gap-1">
          {(["today", "7d", "30d", "all"] as const).map((r) => (
            <button
              key={r}
              onClick={() => handleRangeChange(r)}
              className={`px-1.5 py-0.5 rounded text-[0.6rem] cursor-pointer ${
                range === r
                  ? "bg-sol-blue text-sol-base03"
                  : "bg-sol-base02 text-sol-base01 hover:text-sol-base0"
              }`}
            >
              {r === "today" ? "Today" : r === "7d" ? "7d" : r === "30d" ? "30d" : "All"}
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-1.5">
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic p-2">Sign in to view links</p>
        ) : isLoading && !loadedOnce ? (
          <p className="text-sol-base01 italic p-2">Loading...</p>
        ) : error ? (
          <p className="text-sol-base01 italic p-2">Error loading links</p>
        ) : grouped.length === 0 ? (
          <p className="text-sol-base01 italic p-2">No links found</p>
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
                        {link.timestamp ? formatTime(link.timestamp) : ""}
                      </span>
                      <img
                        src={`https://www.google.com/s2/favicons?domain=${getDomain(link.base_url)}&sz=16`}
                        alt=""
                        className="w-3.5 h-3.5 shrink-0"
                        loading="lazy"
                      />
                      <a
                        href={link.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sol-base0 hover:text-sol-blue truncate text-[0.7rem] min-w-0 flex-1"
                        title={link.url}
                      >
                        {link.title || getDomain(link.base_url)}
                      </a>
                      <DownloadButton link={link} onStatusChange={handleDownloadStatusChange} />
                      <PreviewButton link={link} onPreview={onPreview} />
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
