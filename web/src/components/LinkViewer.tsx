import { useState, useMemo, useCallback } from "react";
import useSWR from "swr";
import { API, authFetch, clearToken } from "../api";

interface Link {
  activity_id: string;
  link_id: string;
  url: string;
  base_url: string;
  title?: string;
  timestamp?: number; // unix ms
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
  const dayEnd = dayStart + 86400000; // end of today (stable)
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
  // Sort days descending, links within day descending
  const entries = [...groups.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  for (const [, links] of entries) {
    links.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
  }
  return entries;
}

const LIMIT = 50;

export default function LinkViewer() {
  const [range, setRange] = useState<DateRange>("7d");
  const [query, setQuery] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [offset, setOffset] = useState(0);
  const [allLinks, setAllLinks] = useState<Link[]>([]);
  const [loadedOnce, setLoadedOnce] = useState(false);

  const { start, end } = getRange(range);
  const params = new URLSearchParams();
  if (start !== undefined) params.set("start", String(start));
  if (end !== undefined) params.set("end", String(end));
  if (query) params.set("query", query);
  params.set("limit", String(LIMIT));
  params.set("offset", String(offset));

  const swrKey = `${API}/api/link/list?${params.toString()}`;

  const { data, isLoading, error } = useSWR<Link[]>(swrKey, fetcher, {
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

  const grouped = useMemo(() => groupByDay(allLinks), [allLinks]);

  return (
    <div className="h-full overflow-y-auto bg-sol-base03 text-sm">
      {/* Top bar */}
      <div className="sticky top-0 z-10 bg-sol-base03 border-b border-sol-base02 px-3 py-2 flex items-center gap-2 flex-wrap">
        <input
          type="text"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
          placeholder="Search links..."
          className="px-2 py-1 rounded text-xs bg-sol-base02 text-sol-base1 border border-sol-base01/20 outline-none focus:border-sol-blue placeholder:text-sol-base01 w-48"
        />
        <button
          onClick={handleSearch}
          className="px-2 py-1 rounded text-xs bg-sol-base02 text-sol-base0 hover:text-sol-base1 cursor-pointer"
        >Search</button>
        <div className="flex gap-1 ml-2">
          {(["today", "7d", "30d", "all"] as const).map((r) => (
            <button
              key={r}
              onClick={() => handleRangeChange(r)}
              className={`px-2 py-1 rounded text-xs cursor-pointer ${
                range === r
                  ? "bg-sol-blue text-sol-base03"
                  : "bg-sol-base02 text-sol-base0 hover:text-sol-base1"
              }`}
            >
              {r === "today" ? "Today" : r === "7d" ? "7 days" : r === "30d" ? "30 days" : "All"}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="px-3 py-2">
        {isLoading && !loadedOnce ? (
          <p className="text-sol-base01 italic">Loading...</p>
        ) : error ? (
          <p className="text-sol-red">Error loading links</p>
        ) : grouped.length === 0 ? (
          <p className="text-sol-base01 italic">No links found</p>
        ) : (
          <>
            {grouped.map(([day, links]) => (
              <div key={day} className="mb-4">
                <h3 className="text-sol-base1 text-xs font-medium mb-1.5 sticky top-[41px] bg-sol-base03 py-1 z-[5] border-b border-sol-base02">
                  {formatDayHeader(day)}
                </h3>
                <div className="space-y-0.5">
                  {links.map((link) => (
                    <div key={link.activity_id} className="flex items-center gap-2 py-1 px-1 rounded hover:bg-sol-base02/50 group">
                      <span className="text-sol-base01 text-xs shrink-0 w-10 text-right">
                        {link.timestamp ? formatTime(link.timestamp) : ""}
                      </span>
                      <img
                        src={`https://www.google.com/s2/favicons?domain=${getDomain(link.base_url)}&sz=16`}
                        alt=""
                        className="w-4 h-4 shrink-0"
                        loading="lazy"
                      />
                      <a
                        href={link.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sol-base0 hover:text-sol-blue truncate"
                        title={link.url}
                      >
                        {link.title || link.base_url}
                      </a>
                      <span className="text-sol-base01 text-xs truncate shrink-0 hidden sm:inline">
                        {getDomain(link.base_url)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
            {hasMore && (
              <button
                onClick={handleLoadMore}
                disabled={isLoading}
                className="w-full py-2 text-center text-xs rounded bg-sol-base02 text-sol-base0 hover:text-sol-base1 cursor-pointer disabled:opacity-50 mb-4"
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
