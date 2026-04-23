import { useCallback, useRef, useState } from "react";
import useSWR from "swr";
import { API, authFetch, clearToken } from "../api";
import RssFeedContextMenu from "./RssFeedContextMenu";

interface ScrapeConfig {
  item_selector?: string;
  title_selector?: string | null;
  link_selector?: string | null;
  link_attr?: string | null;
  date_selector?: string | null;
  date_attr?: string | null;
  date_format?: string | null;
}

interface RssFeed {
  rss_feed_id: string;
  url: string;
  title?: string;
  last_fetched_at?: string;
  last_item_ts?: number;
  feed_type?: string;
  scrape_config?: ScrapeConfig;
  fetch_failure_count?: number;
  created_at?: string;
  updated_at?: string;
}

const FETCH_FAIL_THRESHOLD = 3;
const FETCH_FAIL_COOLDOWN_MS = 24 * 60 * 60 * 1000;

type FeedType = "rss" | "scrape";

interface RssFeedListProps {
  isLoggedIn: boolean;
  onSelectFeed?: (feedId: string, label: string) => void;
  selectedFeedId?: string | null;
}

const fetcher = async (url: string) => {
  const res = await authFetch(url);
  if (res.status === 401) {
    clearToken();
    throw new Error("Unauthorized");
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
};

function getDomain(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function formatRelative(iso?: string): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

export default function RssFeedList({ isLoggedIn, onSelectFeed, selectedFeedId }: RssFeedListProps) {
  const [urlInput, setUrlInput] = useState("");
  const [contextMenu, setContextMenu] = useState<{ feed: RssFeed; x: number; y: number } | null>(null);
  const longPressTimerRef = useRef<number | null>(null);
  const longPressTriggeredRef = useRef(false);
  const [titleInput, setTitleInput] = useState("");
  const [feedType, setFeedType] = useState<FeedType>("rss");
  const [itemSelector, setItemSelector] = useState("");
  const [titleSelector, setTitleSelector] = useState("");
  const [linkSelector, setLinkSelector] = useState("");
  const [linkAttr, setLinkAttr] = useState("");
  const [dateSelector, setDateSelector] = useState("");
  const [dateAttr, setDateAttr] = useState("");
  const [dateFormat, setDateFormat] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [spinning, setSpinning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const swrKey = isLoggedIn ? `${API}/api/rss-feed/list` : null;
  const { data, isLoading, error, mutate } = useSWR<RssFeed[]>(swrKey, fetcher, { revalidateOnFocus: false });

  const handleAdd = useCallback(async () => {
    const url = urlInput.trim();
    if (!url) return;
    if (feedType === "scrape" && !itemSelector.trim()) {
      setErr("item_selector is required for scrape feeds");
      return;
    }
    setSubmitting(true);
    setErr(null);
    try {
      const body: Record<string, any> = {
        url,
        title: titleInput.trim() || null,
        feed_type: feedType,
      };
      if (feedType === "scrape") {
        const cfg: ScrapeConfig = { item_selector: itemSelector.trim() };
        const t = titleSelector.trim();
        if (t) cfg.title_selector = t;
        const l = linkSelector.trim();
        if (l) cfg.link_selector = l;
        const a = linkAttr.trim();
        if (a) cfg.link_attr = a;
        const ds = dateSelector.trim();
        if (ds) cfg.date_selector = ds;
        const da = dateAttr.trim();
        if (da) cfg.date_attr = da;
        const df = dateFormat.trim();
        if (df) cfg.date_format = df;
        body.scrape_config = cfg;
      }
      const res = await authFetch(`${API}/api/rss-feed`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      setUrlInput("");
      setTitleInput("");
      setItemSelector("");
      setTitleSelector("");
      setLinkSelector("");
      setLinkAttr("");
      setDateSelector("");
      setDateAttr("");
      setDateFormat("");
      setFeedType("rss");
      await mutate();
    } catch (e: any) {
      setErr(e?.message || "Failed to add feed");
    } finally {
      setSubmitting(false);
    }
  }, [urlInput, titleInput, feedType, itemSelector, titleSelector, linkSelector, linkAttr, dateSelector, dateAttr, dateFormat, mutate]);

  const handleDelete = useCallback(async (feed: RssFeed) => {
    if (!window.confirm(`Delete feed: ${feed.title || feed.url}?`)) return;
    try {
      const res = await authFetch(`${API}/api/rss-feed/delete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rss_feed_id: feed.rss_feed_id }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await mutate();
    } catch (e: any) {
      setErr(e?.message || "Failed to delete feed");
    }
  }, [mutate]);

  const handleRename = useCallback(async (feed: RssFeed) => {
    const next = window.prompt("New title:", feed.title || "");
    if (next === null) return;
    const trimmed = next.trim();
    try {
      const res = await authFetch(`${API}/api/rss-feed/update`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rss_feed_id: feed.rss_feed_id, title: trimmed }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await mutate();
    } catch (e: any) {
      setErr(e?.message || "Failed to update feed");
    }
  }, [mutate]);

  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      <div className="p-2 border-b border-sol-base02 flex flex-col gap-1.5">
        <div className="flex gap-1.5">
          <input
            type="text"
            placeholder="Feed URL..."
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
            className="flex-1 min-w-0 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
          />
          <button
            onClick={() => { mutate(); setSpinning(true); setTimeout(() => setSpinning(false), 600); }}
            className="px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base01 hover:text-sol-base0 hover:border-sol-base0 transition-colors cursor-pointer"
            title="Refresh"
          >
            <svg className={`w-3.5 h-3.5 ${spinning ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
          </button>
        </div>
        <div className="flex gap-1.5">
          <select
            value={feedType}
            onChange={(e) => setFeedType(e.target.value as FeedType)}
            className="px-1.5 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue text-[0.7rem]"
            title="Feed type"
          >
            <option value="rss">RSS</option>
            <option value="scrape">Scrape</option>
          </select>
          <input
            type="text"
            placeholder="Title (optional)"
            value={titleInput}
            onChange={(e) => setTitleInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
            className="flex-1 min-w-0 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
          />
          <button
            onClick={handleAdd}
            disabled={submitting || !urlInput.trim()}
            className="px-2 py-1 bg-sol-blue text-sol-base03 rounded-md text-[0.7rem] font-medium cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed hover:bg-sol-cyan"
          >
            {submitting ? "Adding..." : "Add"}
          </button>
        </div>
        {feedType === "scrape" && (
          <div className="flex flex-col gap-1 pt-0.5">
            <input
              type="text"
              placeholder="item_selector (required, e.g. a[href^='/news/'])"
              value={itemSelector}
              onChange={(e) => setItemSelector(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
              className="px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
            />
            <div className="flex gap-1.5">
              <input
                type="text"
                placeholder="title_selector (optional, e.g. h3)"
                value={titleSelector}
                onChange={(e) => setTitleSelector(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
                className="flex-1 min-w-0 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
              />
              <input
                type="text"
                placeholder="link_selector (optional)"
                value={linkSelector}
                onChange={(e) => setLinkSelector(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
                className="flex-1 min-w-0 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
              />
              <input
                type="text"
                placeholder="link_attr (href)"
                value={linkAttr}
                onChange={(e) => setLinkAttr(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
                className="w-20 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
              />
            </div>
            <div className="flex gap-1.5">
              <input
                type="text"
                placeholder="date_selector (optional, e.g. time)"
                value={dateSelector}
                onChange={(e) => setDateSelector(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
                className="flex-1 min-w-0 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
              />
              <input
                type="text"
                placeholder="date_attr (e.g. datetime)"
                value={dateAttr}
                onChange={(e) => setDateAttr(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
                className="w-28 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
              />
              <input
                type="text"
                placeholder="date_format (e.g. %Y-%m-%d)"
                value={dateFormat}
                onChange={(e) => setDateFormat(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
                className="w-32 px-2 py-1 bg-sol-base02 border border-sol-base01 rounded-md text-sol-base0 outline-none focus:border-sol-blue"
              />
            </div>
          </div>
        )}
        {err && <div className="text-sol-red text-[0.65rem] px-1">{err}</div>}
      </div>
      <div className="flex-1 overflow-y-auto p-1.5">
        {!isLoggedIn ? (
          <p className="text-sol-base01 italic p-2">Sign in to manage RSS feeds</p>
        ) : isLoading ? (
          <p className="text-sol-base01 italic p-2">Loading...</p>
        ) : error ? (
          <p className="text-sol-base01 italic p-2">Error loading feeds</p>
        ) : !data || data.length === 0 ? (
          <p className="text-sol-base01 italic p-2">No feeds yet. Add one above.</p>
        ) : (
          <div className="space-y-0">
            {data.map((feed) => {
              const isSelected = selectedFeedId === feed.rss_feed_id;
              const cancelLongPress = () => {
                if (longPressTimerRef.current !== null) {
                  window.clearTimeout(longPressTimerRef.current);
                  longPressTimerRef.current = null;
                }
              };
              return (
                <div
                  key={feed.rss_feed_id}
                  onClick={() => {
                    if (longPressTriggeredRef.current) {
                      longPressTriggeredRef.current = false;
                      return;
                    }
                    if (onSelectFeed) onSelectFeed(feed.rss_feed_id, feed.title || getDomain(feed.url));
                  }}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    setContextMenu({ feed, x: e.clientX, y: e.clientY });
                  }}
                  onPointerDown={(e) => {
                    if (e.pointerType !== "touch") return;
                    longPressTriggeredRef.current = false;
                    cancelLongPress();
                    const x = e.clientX;
                    const y = e.clientY;
                    longPressTimerRef.current = window.setTimeout(() => {
                      longPressTriggeredRef.current = true;
                      setContextMenu({ feed, x, y });
                    }, 500);
                  }}
                  onPointerMove={(e) => { if (e.pointerType === "touch") cancelLongPress(); }}
                  onPointerUp={(e) => { if (e.pointerType === "touch") cancelLongPress(); }}
                  onPointerCancel={cancelLongPress}
                  className={`flex items-center gap-1.5 py-1 px-1 rounded group cursor-pointer ${
                    isSelected ? "bg-sol-base02" : "hover:bg-sol-base02/50"
                  }`}
                >
                  <img
                    src={`https://www.google.com/s2/favicons?domain=${getDomain(feed.url)}&sz=16`}
                    alt=""
                    className="w-3.5 h-3.5 shrink-0"
                    loading="lazy"
                  />
                  <div className="min-w-0 flex-1 flex flex-col">
                    <div className="flex items-center gap-1 min-w-0">
                      <span
                        className={`text-left truncate text-[0.7rem] ${isSelected ? "text-sol-blue" : "text-sol-base0"}`}
                        title={feed.title || "(untitled)"}
                      >
                        {feed.title || getDomain(feed.url)}
                      </span>
                      {feed.feed_type === "scrape" && (
                        <span
                          className="shrink-0 px-1 py-0 bg-sol-base02 border border-sol-yellow/50 rounded text-sol-yellow text-[0.55rem] font-medium leading-tight"
                          title={feed.scrape_config ? JSON.stringify(feed.scrape_config, null, 2) : "scrape feed"}
                        >
                          SCRAPE
                        </span>
                      )}
                      {(() => {
                        const failures = feed.fetch_failure_count ?? 0;
                        const lastMs = feed.last_fetched_at ? Date.parse(feed.last_fetched_at) : NaN;
                        const pausedUntil = !Number.isNaN(lastMs) && failures >= FETCH_FAIL_THRESHOLD
                          ? lastMs + FETCH_FAIL_COOLDOWN_MS
                          : 0;
                        const paused = pausedUntil > Date.now();
                        if (paused) {
                          const untilIso = new Date(pausedUntil).toISOString();
                          return (
                            <span
                              className="shrink-0 px-1 py-0 bg-sol-base02 border border-sol-red/60 rounded text-sol-red text-[0.55rem] font-medium leading-tight"
                              title={`Paused until ${untilIso}; ${failures} consecutive failures`}
                            >
                              PAUSED
                            </span>
                          );
                        }
                        if (failures >= 1) {
                          return (
                            <span
                              className="shrink-0 px-1 py-0 text-sol-yellow text-[0.55rem] font-medium leading-tight"
                              title={`${failures} consecutive failure${failures > 1 ? "s" : ""}`}
                            >
                              f:{failures}
                            </span>
                          );
                        }
                        return null;
                      })()}
                    </div>
                    <a
                      href={feed.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="text-sol-base01 hover:text-sol-cyan truncate text-[0.6rem]"
                      title={feed.url}
                    >
                      {feed.url}
                    </a>
                  </div>
                  <span className="text-sol-base01 text-[0.6rem] shrink-0 whitespace-nowrap" title={feed.last_fetched_at || "never fetched"}>
                    {formatRelative(feed.last_fetched_at)}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
      {contextMenu && (
        <RssFeedContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          onClose={() => setContextMenu(null)}
          onRename={() => handleRename(contextMenu.feed)}
          onDelete={() => handleDelete(contextMenu.feed)}
        />
      )}
    </div>
  );
}
