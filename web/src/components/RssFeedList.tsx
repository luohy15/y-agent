import { useCallback, useState } from "react";
import useSWR from "swr";
import { API, authFetch, clearToken } from "../api";

interface ScrapeConfig {
  item_selector?: string;
  title_selector?: string | null;
  link_selector?: string | null;
  link_attr?: string | null;
}

interface RssFeed {
  rss_feed_id: string;
  url: string;
  title?: string;
  last_fetched_at?: string;
  last_item_ts?: number;
  feed_type?: string;
  scrape_config?: ScrapeConfig;
  created_at?: string;
  updated_at?: string;
}

type FeedType = "rss" | "scrape";

interface RssFeedListProps {
  isLoggedIn: boolean;
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

export default function RssFeedList({ isLoggedIn }: RssFeedListProps) {
  const [urlInput, setUrlInput] = useState("");
  const [titleInput, setTitleInput] = useState("");
  const [feedType, setFeedType] = useState<FeedType>("rss");
  const [itemSelector, setItemSelector] = useState("");
  const [titleSelector, setTitleSelector] = useState("");
  const [linkSelector, setLinkSelector] = useState("");
  const [linkAttr, setLinkAttr] = useState("");
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
      setFeedType("rss");
      await mutate();
    } catch (e: any) {
      setErr(e?.message || "Failed to add feed");
    } finally {
      setSubmitting(false);
    }
  }, [urlInput, titleInput, feedType, itemSelector, titleSelector, linkSelector, linkAttr, mutate]);

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
            {data.map((feed) => (
              <div
                key={feed.rss_feed_id}
                className="flex items-center gap-1.5 py-1 px-1 rounded hover:bg-sol-base02/50 group"
              >
                <img
                  src={`https://www.google.com/s2/favicons?domain=${getDomain(feed.url)}&sz=16`}
                  alt=""
                  className="w-3.5 h-3.5 shrink-0"
                  loading="lazy"
                />
                <div className="min-w-0 flex-1 flex flex-col">
                  <div className="flex items-center gap-1 min-w-0">
                    <button
                      onClick={() => handleRename(feed)}
                      className="text-left text-sol-base0 hover:text-sol-blue truncate text-[0.7rem] cursor-pointer"
                      title={`Rename — ${feed.title || "(untitled)"}`}
                    >
                      {feed.title || getDomain(feed.url)}
                    </button>
                    {feed.feed_type === "scrape" && (
                      <span
                        className="shrink-0 px-1 py-0 bg-sol-base02 border border-sol-yellow/50 rounded text-sol-yellow text-[0.55rem] font-medium leading-tight"
                        title={feed.scrape_config ? JSON.stringify(feed.scrape_config, null, 2) : "scrape feed"}
                      >
                        SCRAPE
                      </span>
                    )}
                  </div>
                  <a
                    href={feed.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sol-base01 hover:text-sol-cyan truncate text-[0.6rem]"
                    title={feed.url}
                  >
                    {feed.url}
                  </a>
                </div>
                <span className="text-sol-base01 text-[0.6rem] shrink-0 whitespace-nowrap" title={feed.last_fetched_at || "never fetched"}>
                  {formatRelative(feed.last_fetched_at)}
                </span>
                <button
                  onClick={() => handleDelete(feed)}
                  className="shrink-0 w-4 h-4 flex items-center justify-center text-sol-base01 opacity-0 group-hover:opacity-100 hover:text-sol-red cursor-pointer"
                  title="Delete feed"
                >
                  <svg className="w-3 h-3" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd"/></svg>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
