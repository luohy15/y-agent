import { useState, useMemo, useCallback, useRef } from "react";
import useSWR from "swr";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { API, authFetch, clearToken } from "../api";

interface Link {
  activity_id: string;
  link_id: string;
  url: string;
  base_url: string;
  title?: string;
  timestamp?: number; // unix ms
  download_status?: string | null; // pending/downloading/done/failed
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
  const dayEnd = dayStart + 86400000; // end of today (stable)
  switch (range) {
    case "today": return { start: dayStart, end: dayEnd };
    case "7d": return { start: dayStart - 6 * 86400000, end: dayEnd };
    case "30d": return { start: dayStart - 29 * 86400000, end: dayEnd };
  }
}

function stripFragment(url: string): string {
  const i = url.indexOf('#');
  return i === -1 ? url : url.substring(0, i);
}

function isActivityLevel(url: string, baseUrl: string): boolean {
  return stripFragment(url) !== baseUrl;
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

async function downloadLinks(urls: string[]): Promise<any> {
  const res = await authFetch(`${API}/api/link/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ urls }),
  });
  return res.json();
}

async function fetchLinkContent(linkId: string, url?: string, baseUrl?: string): Promise<string> {
  let endpoint = `${API}/api/link/content?link_id=${encodeURIComponent(linkId)}`;
  if (url && baseUrl && isActivityLevel(url, baseUrl)) {
    endpoint += `&url=${encodeURIComponent(url)}`;
  }
  const res = await authFetch(endpoint);
  if (!res.ok) throw new Error("Failed to fetch content");
  const data = await res.json();
  return data.content;
}

function DownloadButton({ link, onStatusChange }: { link: Link; onStatusChange: (url: string, status: string) => void }) {
  const status = link.download_status;
  const isLoading = status === "pending" || status === "downloading";

  const handleClick = async () => {
    if (isLoading || status === "done") return;
    onStatusChange(link.url, "pending");
    try {
      await downloadLinks([link.url]);
    } catch {
      onStatusChange(link.url, "failed");
    }
  };

  if (isLoading) {
    return (
      <span className="shrink-0 w-5 h-5 flex items-center justify-center text-sol-yellow" title="Downloading...">
        <svg className="animate-spin w-3.5 h-3.5" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" strokeLinecap="round"/></svg>
      </span>
    );
  }
  if (status === "done") {
    return (
      <span className="shrink-0 w-5 h-5 flex items-center justify-center text-sol-green" title="Downloaded">
        <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/></svg>
      </span>
    );
  }
  if (status === "failed") {
    return (
      <button onClick={handleClick} className="shrink-0 w-5 h-5 flex items-center justify-center text-sol-red hover:text-sol-orange cursor-pointer" title="Failed - click to retry">
        <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clipRule="evenodd"/></svg>
      </button>
    );
  }
  // No status or null — show archive button
  return (
    <button onClick={handleClick} className="shrink-0 w-5 h-5 flex items-center justify-center text-sol-base01 opacity-0 group-hover:opacity-100 hover:text-sol-blue cursor-pointer" title="Download content">
      <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z"/></svg>
    </button>
  );
}

function PreviewButton({ link, onPreview }: { link: Link; onPreview: (link: Link) => void }) {
  if (link.download_status !== "done") return null;
  return (
    <button
      onClick={() => onPreview(link)}
      className="shrink-0 w-5 h-5 flex items-center justify-center text-sol-base01 opacity-0 group-hover:opacity-100 hover:text-sol-cyan cursor-pointer"
      title="Preview content"
    >
      <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
        <path d="M10 12a2 2 0 100-4 2 2 0 000 4z"/>
        <path fillRule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clipRule="evenodd"/>
      </svg>
    </button>
  );
}

function PreviewPanel({ link, content, loading, onClose }: {
  link: Link;
  content: string | null;
  loading: boolean;
  onClose: () => void;
}) {
  return (
    <div className="h-full flex flex-col bg-sol-base03 border-l border-sol-base02">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-sol-base02 shrink-0">
        <button
          onClick={onClose}
          className="shrink-0 w-5 h-5 flex items-center justify-center text-sol-base01 hover:text-sol-base1 cursor-pointer"
          title="Close preview"
        >
          <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd"/>
          </svg>
        </button>
        <span className="text-sol-base1 text-xs font-medium truncate">{link.title || link.base_url}</span>
      </div>
      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {loading ? (
          <div className="flex items-center gap-2 text-sol-base01">
            <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" strokeLinecap="round"/></svg>
            <span className="text-xs">Loading content...</span>
          </div>
        ) : content ? (
          <div className="prose prose-sm prose-invert max-w-none text-sol-base0 [&_h1]:text-sol-base1 [&_h2]:text-sol-base1 [&_h3]:text-sol-base1 [&_a]:text-sol-blue [&_code]:text-sol-cyan [&_pre]:bg-sol-base02 [&_pre]:rounded [&_blockquote]:border-sol-base01 [&_hr]:border-sol-base02 [&_table]:text-sol-base0 [&_th]:text-sol-base1 [&_img]:rounded">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </div>
        ) : (
          <p className="text-sol-base01 text-xs italic">No content available</p>
        )}
      </div>
    </div>
  );
}

const LIMIT = 50;

export default function LinkViewer() {
  const [range, setRange] = useState<DateRange>("7d");
  const [query, setQuery] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [offset, setOffset] = useState(0);
  const [allLinks, setAllLinks] = useState<Link[]>([]);
  const [loadedOnce, setLoadedOnce] = useState(false);

  // Preview state
  const [previewLink, setPreviewLink] = useState<Link | null>(null);
  const [previewContent, setPreviewContent] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const contentCache = useRef<Map<string, string>>(new Map());

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

  const handleDownloadStatusChange = useCallback((url: string, status: string) => {
    setAllLinks((prev) =>
      prev.map((l) => l.url === url ? { ...l, download_status: status } : l)
    );
  }, []);

  const handlePreview = useCallback(async (link: Link) => {
    setPreviewLink(link);
    // Use url as cache key for activity-level content, link_id for link-level
    const cacheKey = isActivityLevel(link.url, link.base_url) ? link.url : link.link_id;
    const cached = contentCache.current.get(cacheKey);
    if (cached) {
      setPreviewContent(cached);
      return;
    }
    setPreviewContent(null);
    setPreviewLoading(true);
    try {
      const content = await fetchLinkContent(link.link_id, link.url, link.base_url);
      contentCache.current.set(cacheKey, content);
      setPreviewContent(content);
    } catch {
      setPreviewContent(null);
    } finally {
      setPreviewLoading(false);
    }
  }, []);

  const handleClosePreview = useCallback(() => {
    setPreviewLink(null);
    setPreviewContent(null);
  }, []);

  const grouped = useMemo(() => groupByDay(allLinks), [allLinks]);

  return (
    <div className="h-full flex">
      {/* Link list */}
      <div className={`h-full overflow-y-auto bg-sol-base03 text-sm ${previewLink ? "w-1/2" : "w-full"}`}>
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
                        <DownloadButton link={link} onStatusChange={handleDownloadStatusChange} />
                        <PreviewButton link={link} onPreview={handlePreview} />
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

      {/* Preview panel */}
      {previewLink && (
        <div className="w-1/2 h-full">
          <PreviewPanel
            link={previewLink}
            content={previewContent}
            loading={previewLoading}
            onClose={handleClosePreview}
          />
        </div>
      )}
    </div>
  );
}
