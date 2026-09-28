import { ListEmpty } from "./ListStates";

// Presentational link list for the logged-out public trace projection. The
// authenticated Links list lives in the `link` / `rss` modules (todo 3708);
// modules cannot mount on a public page, so this items-only path stays here.
// Clicking a row opens the original URL in a new tab (link-out).
export interface Link {
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

export default function PublicLinkList({ items }: { items: Link[] }) {
  const groups = groupByDay(items);
  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      <div className="flex-1 overflow-y-auto p-1.5">
        {groups.length === 0 ? (
          <ListEmpty label="links" />
        ) : (
          groups.map(([day, links]) => (
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
                      onClick={() => window.open(link.url, "_blank", "noopener,noreferrer")}
                      className="text-sol-base0 hover:text-sol-cyan truncate text-[0.7rem] min-w-0 flex-1 text-left cursor-pointer bg-transparent border-0 p-0"
                      title={`Open original page: ${link.url}`}
                    >
                      {link.title || getDomain(link.base_url)}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
