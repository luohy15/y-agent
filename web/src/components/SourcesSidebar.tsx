import { citationHostname } from "./citationDomain";
import { normalizeLinks } from "./citationLinks";
import type { CitationLink } from "./MessageList";

interface SourcesSidebarProps {
  links: CitationLink[];
  onClose: () => void;
}

export default function SourcesSidebar({ links, onClose }: SourcesSidebarProps) {
  const validLinks = normalizeLinks(links);

  return (
    <aside className="absolute inset-y-0 right-0 z-20 flex w-full flex-col border-l border-sol-base02 bg-sol-base03 shadow-xl sm:static sm:w-80 sm:shrink-0 sm:shadow-none">
      <div className="flex shrink-0 items-center justify-between border-b border-sol-base02 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-sol-base1">Sources</h2>
          <div className="text-xs text-sol-base01">{validLinks.length} source{validLinks.length === 1 ? "" : "s"}</div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded px-2 py-1 text-lg leading-none text-sol-base01 hover:bg-sol-base02 hover:text-sol-base1"
          aria-label="Close sources"
        >
          ×
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {validLinks.map((link, index) => {
          const hostname = citationHostname(link.url);
          const title = link.title || hostname;
          return (
            <article key={`${link.url}-${index}`} className="rounded-lg border border-sol-base02 bg-sol-base02/50 p-3">
              <div className="mb-1 flex items-start gap-2">
                <span className="mt-0.5 shrink-0 rounded bg-sol-base03 px-1.5 py-0.5 font-mono text-[0.65rem] text-sol-base01">[{index + 1}]</span>
                <a
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="min-w-0 text-sm font-medium leading-snug text-sol-blue hover:underline"
                >
                  {title}
                </a>
              </div>
              <div className="truncate pl-8 text-xs text-sol-base01">{hostname}</div>
              {link.snippet && <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-sol-base0">{link.snippet}</p>}
              {link.last_updated && <div className="mt-2 text-[0.65rem] text-sol-base01">Updated {link.last_updated}</div>}
            </article>
          );
        })}
      </div>
    </aside>
  );
}
