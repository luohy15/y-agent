import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSlug from "rehype-slug";
import { parseLocalFileReference } from "../../utils/localFileLinks";
import { parseFrontMatter } from "../../utils/markdown";
import { extractMarkdownHeadings } from "../../utils/markdownExport";

function FrontMatterCard({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return null;
  const title = typeof data.title === "string" ? data.title : undefined;
  const tagsRaw = data.tags ?? data.tag;
  const tagList: string[] = Array.isArray(tagsRaw)
    ? tagsRaw.map(String).filter((s) => s.length > 0)
    : typeof tagsRaw === "string" && tagsRaw.trim() !== ""
    ? tagsRaw.split(",").map((s) => s.trim()).filter(Boolean)
    : [];
  const rest = entries.filter(([k, v]) => {
    if (k === "title" || k === "tags" || k === "tag") return false;
    if (v === "" || v === null || v === undefined) return false;
    if (Array.isArray(v) && v.length === 0) return false;
    return true;
  });
  if (!title && tagList.length === 0 && rest.length === 0) return null;

  const formatValue = (v: unknown): string => {
    if (v === null || v === undefined) return "";
    if (Array.isArray(v)) return v.map(String).join(", ");
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  };

  return (
    <div className="not-prose mb-4 rounded border border-sol-base02 bg-sol-base02/30 px-4 py-3">
      {title && (
        <div className="text-sol-base1 font-semibold text-base break-words mb-2">{title}</div>
      )}
      {tagList.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {tagList.map((t) => (
            <span
              key={t}
              className="inline-flex items-center px-1.5 py-0.5 rounded text-[0.65rem] font-mono bg-sol-base02 text-sol-base01"
            >
              {t}
            </span>
          ))}
        </div>
      )}
      {rest.length > 0 && (
        <div className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs">
          {rest.map(([k, v]) => (
            <Fragment key={k}>
              <div className="text-sol-base01">{k}</div>
              <div className="text-sol-base0 break-words">{formatValue(v)}</div>
            </Fragment>
          ))}
        </div>
      )}
    </div>
  );
}

function MarkdownToc({ headings, articleRef, onSelect }: { headings: { text: string; id: string; level: number }[]; articleRef: React.RefObject<HTMLElement | null>; onSelect?: () => void }) {
  return (
    <ul className="space-y-1">
      {headings.map((h) => (
        <li key={h.id} className={h.level === 3 ? "pl-3" : ""}>
          <a
            href={`#${h.id}`}
            onClick={(e) => {
              e.preventDefault();
              // Scope the lookup to this tab's article: FileViewer keeps every open
              // tab mounted (hidden) to preserve scroll, so a global getElementById
              // can resolve to a same-slug heading in another (hidden) note tab and
              // scroll nothing. querySelector within the active article fixes that.
              const root = articleRef.current ?? document;
              root.querySelector(`#${CSS.escape(h.id)}`)?.scrollIntoView({ block: "start" });
              onSelect?.();
            }}
            className="text-xs text-sol-base0 hover:text-sol-blue no-underline block truncate cursor-pointer"
          >
            {h.text}
          </a>
        </li>
      ))}
    </ul>
  );
}

function resolveRelativePath(currentFilePath: string, href: string): string {
  const dir = currentFilePath.includes("/") ? currentFilePath.substring(0, currentFilePath.lastIndexOf("/") + 1) : "";
  const parts = (dir + href).split("/");
  const resolved: string[] = [];
  for (const part of parts) {
    if (part === "..") resolved.pop();
    else if (part !== ".") resolved.push(part);
  }
  return resolved.join("/");
}

function isRelativeLink(href: string): boolean {
  return !/^(https?:\/\/|mailto:|#|\/)/.test(href);
}

function isAbsoluteHttpLink(href: string): boolean {
  return /^https?:\/\//i.test(href);
}

export interface MarkdownPreviewProps {
  content: string;
  currentFilePath?: string;
  onOpenFile?: (path: string, line?: number) => void;
  onExternalLinkClick?: (url: string) => void;
}

/**
 * Shared markdown renderer used by FileViewer (auth + public) and demo file tabs.
 * One definition so production and demo share the same preview path.
 */
export default function MarkdownPreview({ content, currentFilePath, onOpenFile, onExternalLinkClick }: MarkdownPreviewProps) {
  const [tocOpen, setTocOpen] = useState(false);
  const [tocCollapsed, setTocCollapsed] = useState(() => localStorage.getItem("markdownTocCollapsed") === "true");
  const { data: frontMatter, body } = useMemo(() => parseFrontMatter(content ?? ""), [content]);
  const articleRef = useRef<HTMLDivElement | null>(null);
  const [headings, setHeadings] = useState<{ text: string; id: string; level: number }[]>([]);

  useEffect(() => {
    const article = articleRef.current;
    if (!article) {
      setHeadings([]);
      return;
    }
    const raf = window.requestAnimationFrame(() => {
      setHeadings(extractMarkdownHeadings(article));
    });
    return () => window.cancelAnimationFrame(raf);
  }, [body]);

  return (
    <div className="flex h-full">
      <div ref={articleRef} className="flex-1 min-w-0 overflow-auto p-4 prose prose-invert prose-sm max-w-none text-sol-base0 break-words [&_pre]:overflow-x-auto [&_table]:overflow-x-auto [&_img]:max-w-full relative">
        <FrontMatterCard data={frontMatter} />
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeSlug]}
          components={{
            a: ({ href, children, ...props }) => {
              const fileRef = parseLocalFileReference(href, { allowRelative: false });
              if (fileRef && onOpenFile) {
                return (
                  <a
                    href={href}
                    onClick={(e) => {
                      e.preventDefault();
                      onOpenFile(fileRef.path, fileRef.line);
                    }}
                    {...props}
                  >
                    {children}
                  </a>
                );
              }
              if (href && currentFilePath && onOpenFile && isRelativeLink(href)) {
                return (
                  <a
                    href={href}
                    onClick={(e) => {
                      e.preventDefault();
                      onOpenFile(resolveRelativePath(currentFilePath, href));
                    }}
                    {...props}
                  >
                    {children}
                  </a>
                );
              }
              if (href && onExternalLinkClick && isAbsoluteHttpLink(href)) {
                return (
                  <a
                    href={href}
                    onClick={(e) => {
                      e.preventDefault();
                      onExternalLinkClick(href);
                    }}
                    {...props}
                  >
                    {children}
                  </a>
                );
              }
              return <a href={href} {...props}>{children}</a>;
            },
          }}
        >
          {body}
        </ReactMarkdown>
      </div>
      {/* Desktop (lg+): sidebar TOC */}
      {headings.length > 0 && (
        <nav className={`hidden lg:flex flex-col shrink-0 border-l border-sol-base02 transition-all duration-200 ${tocCollapsed ? "w-8" : "w-48"}`}>
          <button
            onClick={() => setTocCollapsed((v) => { const next = !v; localStorage.setItem("markdownTocCollapsed", String(next)); return next; })}
            className="p-2 text-sol-base01 hover:text-sol-base0 cursor-pointer text-xs shrink-0"
            title={tocCollapsed ? "Expand TOC" : "Collapse TOC"}
          >
            {tocCollapsed ? "◀" : "▶"}
          </button>
          {!tocCollapsed && (
            <div className="overflow-y-auto px-3 pb-3">
              <div className="text-xs text-sol-base01 mb-2">Contents</div>
              <MarkdownToc headings={headings} articleRef={articleRef} />
            </div>
          )}
        </nav>
      )}
      {/* Tablet (md to lg): dropdown TOC button */}
      {headings.length > 0 && (
        <div className="hidden md:block lg:hidden absolute top-2 right-2 z-10">
          <button
            onClick={() => setTocOpen((v) => !v)}
            className="w-8 h-8 rounded bg-sol-base02 border border-sol-base01 text-sol-base1 flex items-center justify-center cursor-pointer hover:bg-sol-base01/30"
            title="Table of contents"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" />
              <line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" />
            </svg>
          </button>
          {tocOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setTocOpen(false)} />
              <nav className="absolute right-0 top-10 z-50 w-56 max-h-64 overflow-y-auto bg-sol-base03 border border-sol-base01 rounded shadow-float p-3">
                <div className="text-xs text-sol-base01 mb-2">Contents</div>
                <MarkdownToc headings={headings} articleRef={articleRef} onSelect={() => setTocOpen(false)} />
              </nav>
            </>
          )}
        </div>
      )}
      {/* Mobile: FAB + popover TOC */}
      {headings.length > 0 && (
        <div className="md:hidden">
          <button
            onClick={() => setTocOpen((v) => !v)}
            className="fixed right-4 bottom-14 z-40 w-10 h-10 rounded-full bg-sol-base02 border border-sol-base01 text-sol-base1 flex items-center justify-center shadow-float cursor-pointer"
            title="Table of contents"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" />
              <line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" />
            </svg>
          </button>
          {tocOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setTocOpen(false)} />
              <nav className="fixed right-4 bottom-26 z-50 w-56 max-h-64 overflow-y-auto bg-sol-base03 border border-sol-base01 rounded shadow-float p-3">
                <div className="text-xs text-sol-base01 mb-2">Contents</div>
                <MarkdownToc headings={headings} articleRef={articleRef} onSelect={() => setTocOpen(false)} />
              </nav>
            </>
          )}
        </div>
      )}
    </div>
  );
}
