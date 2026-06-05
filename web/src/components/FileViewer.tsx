import { useEffect, useState, useRef, useMemo, useCallback, Fragment } from "react";
import { useSWRConfig } from "swr";
import { API, authFetch } from "../api";
import hljs from "highlight.js";
import "highlight.js/styles/base16/solarized-dark.min.css";
import TodoViewer from "./TodoViewer";
import CalendarViewer from "./CalendarViewer";
import FinanceViewer from "./FinanceViewer";
import EmailViewer from "./EmailViewer";
import DevViewer from "./DevViewer";
import BotViewer from "./BotViewer";
import DiffViewer from "./DiffViewer";
import TraceView from "./TraceView";
import LinkList from "./LinkList";
import CodeEditor from "./CodeEditor";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSlug from "rehype-slug";
import { parseLocalFileReference } from "../utils/localFileLinks";
import ArtifactView, { type ArtifactMode, type ArtifactType } from "./ArtifactView";


interface FileViewerProps {
  openFiles: string[];
  activeFile: string | null;
  onSelectFile: (path: string, line?: number) => void;
  onCloseFile: (path: string) => void;
  onReorderFiles: (files: string[]) => void;
  vmName?: string | null;
  workDir?: string;
  defaultWorkDir?: string;
  diffFiles?: Set<string>;
  artifactTabs?: Record<string, { type: ArtifactType; spec: string }>;
  isLoggedIn?: boolean;
  selectedTraceId?: string | null;
  selectedLinkId?: string | null;
  selectedLinkLinkId?: string | null;
  selectedLinkContentKey?: string | null;
  selectedEntityId?: string | null;
  selectedFeedId?: string | null;
  selectedFeedLabel?: string | null;
  onClearFeed?: () => void;
  onSelectChat?: (chatId: string) => void;
  onPreviewLink?: (activityId: string) => void;
  onPreviewLinkFull?: (activityId: string, contentKey: string | null) => void;
  onExternalLinkClick?: (url: string) => void;
  previewFile?: string | null;
  onPinFile?: (path: string) => void;
  onPreviewFile?: (path: string, line?: number) => void;
  pendingLines?: Record<string, number | undefined>;
  onConsumeLine?: (path: string) => void;
  onChatListRefresh?: () => void;
  onTraceTodoDirtyChange?: (dirty: boolean) => void;
  // Public trace projection: render note tabs keyed by note `share_id`, with content
  // fetched from the public S3-backed `/api/note/share` endpoint (no auth, no /api/file/*).
  mode?: "public";
  noteMeta?: Record<string, { content_key: string; front_matter?: Record<string, unknown> | null }>;
}

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "gif", "bmp", "svg", "webp", "ico"]);
const PDF_EXTS = new Set(["pdf"]);

function getExt(path: string): string {
  const dot = path.lastIndexOf(".");
  return dot >= 0 ? path.slice(dot + 1).toLowerCase() : "";
}

function getFileName(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash >= 0 ? path.slice(slash + 1) : path;
}

function downloadAsMarkdown(filename: string, content: string) {
  const base = filename.replace(/\.md$/i, "");
  const safe = (base || "download").replace(/[\\/:*?"<>|]/g, "_");
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${safe}.md`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function getBreadcrumb(path: string): string[] {
  return path.replace(/^\.\//, "").split("/").filter(Boolean);
}

function artifactLabel(path: string, artifactTabs?: Record<string, { type: ArtifactType; spec: string }>): string {
  return artifactTabs?.[path]?.type ?? "artifact";
}

interface FileCache {
  content?: string | null;
  summary?: string | null;
  blobUrl?: string;
  loading: boolean;
  error?: string;
  linkTitle?: string;
  linkUrl?: string;
  summaryContentKey?: string;
}

function FileContentTable({ filePath, content }: { filePath: string; content: string }) {
  const highlightedHtml = useMemo(() => {
    const lang = getExt(filePath);
    try {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(content, { language: lang }).value;
      }
      return hljs.highlightAuto(content).value;
    } catch {
      return null;
    }
  }, [content, filePath]);

  const lines = (content ?? "").split("\n");
  const highlightedLines = highlightedHtml?.split("\n");

  return (
    <table className="text-sm font-mono leading-relaxed w-full border-collapse">
      <tbody>
        {lines.map((line, i) => (
          <tr key={i}>
            <td className="select-none text-right pr-3 pl-2 text-sol-base01 border-r border-sol-base02 align-top bg-sol-base03 sticky left-0 w-[1%]">
              {i + 1}
            </td>
            {highlightedLines ? (
              <td className="pl-4 pr-3 whitespace-pre-wrap break-all hljs" dangerouslySetInnerHTML={{ __html: highlightedLines[i] ?? "" }} />
            ) : (
              <td className="pl-4 pr-3 text-sol-base0 whitespace-pre-wrap break-all">
                {line}
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function parseFrontMatterScalar(raw: string): string {
  let v = raw.trim();
  if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
    v = v.slice(1, -1);
  }
  return v;
}

function parseFrontMatter(content: string): { data: Record<string, unknown>; body: string } {
  const m = content.match(/^---\r?\n([\s\S]*?)\r?\n---(\r?\n|$)/);
  if (!m) return { data: {}, body: content };
  const yaml = m[1];
  const body = content.slice(m[0].length);
  const data: Record<string, unknown> = {};
  const lines = yaml.split(/\r?\n/);
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") { i++; continue; }
    const kv = line.match(/^([A-Za-z_][\w.-]*)\s*:\s*(.*)$/);
    if (!kv) { i++; continue; }
    const key = kv[1];
    const rest = kv[2];
    if (rest.trim() === "") {
      const items: string[] = [];
      let j = i + 1;
      while (j < lines.length) {
        const item = lines[j].match(/^\s+-\s+(.*)$/);
        if (!item) break;
        items.push(parseFrontMatterScalar(item[1]));
        j++;
      }
      data[key] = items.length > 0 ? items : "";
      i = items.length > 0 ? j : i + 1;
      continue;
    }
    const val = rest.trim();
    if (val.startsWith("[") && val.endsWith("]")) {
      const inner = val.slice(1, -1).trim();
      data[key] = inner === "" ? [] : inner.split(",").map((s) => parseFrontMatterScalar(s));
    } else {
      data[key] = parseFrontMatterScalar(val);
    }
    i++;
  }
  return { data, body };
}

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
    <div className="not-prose mb-4 rounded-lg border border-sol-base02 bg-sol-base02/30 px-4 py-3">
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

function MarkdownToc({ headings, onSelect }: { headings: { text: string; id: string; level: number }[]; onSelect?: () => void }) {
  return (
    <ul className="space-y-1">
      {headings.map((h) => (
        <li key={h.id} className={h.level === 3 ? "pl-3" : ""}>
          <a
            href={`#${h.id}`}
            onClick={(e) => {
              e.preventDefault();
              document.getElementById(h.id)?.scrollIntoView({ block: "start" });
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

function MarkdownPreview({ content, currentFilePath, onOpenFile, onExternalLinkClick }: { content: string; currentFilePath?: string; onOpenFile?: (path: string, line?: number) => void; onExternalLinkClick?: (url: string) => void }) {
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
      const els = Array.from(article.querySelectorAll<HTMLElement>("h2[id], h3[id]"));
      setHeadings(els.map((el) => ({ id: el.id, text: el.textContent || "", level: el.tagName === "H3" ? 3 : 2 })));
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
              <MarkdownToc headings={headings} />
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
              <nav className="absolute right-0 top-10 z-50 w-56 max-h-64 overflow-y-auto bg-sol-base03 border border-sol-base01 rounded-lg shadow-xl p-3">
                <div className="text-xs text-sol-base01 mb-2">Contents</div>
                <MarkdownToc headings={headings} onSelect={() => setTocOpen(false)} />
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
            className="fixed right-4 bottom-14 z-40 w-10 h-10 rounded-full bg-sol-base02 border border-sol-base01 text-sol-base1 flex items-center justify-center shadow-lg cursor-pointer"
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
              <nav className="fixed right-4 bottom-26 z-50 w-56 max-h-64 overflow-y-auto bg-sol-base03 border border-sol-base01 rounded-lg shadow-xl p-3">
                <div className="text-xs text-sol-base01 mb-2">Contents</div>
                <MarkdownToc headings={headings} onSelect={() => setTocOpen(false)} />
              </nav>
            </>
          )}
        </div>
      )}
    </div>
  );
}

async function fetchLinkContent({ activityId, linkId }: { activityId?: string | null; linkId?: string | null }): Promise<{ title?: string; url?: string; content: string | null; summary?: string | null; summaryContentKey?: string }> {
  const qs = activityId
    ? `activity_id=${encodeURIComponent(activityId)}`
    : linkId
    ? `link_id=${encodeURIComponent(linkId)}`
    : "";
  const res = await authFetch(`${API}/api/link/content?${qs}`);
  if (!res.ok) throw new Error("Failed to fetch content");
  const data = await res.json();
  return { title: data.title, url: data.url || data.base_url, content: data.content, summary: data.summary, summaryContentKey: data.summary_content_key };
}

function LinkContentView({ activityId, linkId, cache, setCache, raw, onExternalLinkClick }: { activityId: string | null; linkId?: string | null; cache: Record<string, FileCache>; setCache: React.Dispatch<React.SetStateAction<Record<string, FileCache>>>; raw?: boolean; onExternalLinkClick?: (url: string) => void }) {
  const cacheKey = activityId ? `link:activity:${activityId}` : linkId ? `link:link:${linkId}` : "";
  const fileData = cacheKey ? cache[cacheKey] : undefined;
  const [showSummary, setShowSummary] = useState(false);
  const [generatingSummary, setGeneratingSummary] = useState(false);

  useEffect(() => {
    if (!cacheKey) return;
    if (!activityId && !linkId) return;
    if (fileData && !fileData.error) return;

    setCache((prev) => ({ ...prev, [cacheKey]: { loading: true } }));
    fetchLinkContent({ activityId, linkId })
      .then(({ title, url, content, summary, summaryContentKey }) => setCache((prev) => ({ ...prev, [cacheKey]: { content, summary, summaryContentKey, linkTitle: title, linkUrl: url, loading: false } })))
      .catch((e) => setCache((prev) => ({ ...prev, [cacheKey]: { loading: false, error: e.message } })));
  }, [activityId, linkId, fileData, setCache, cacheKey]);

  const handleGenerateSummary = async () => {
    if (!cacheKey || generatingSummary) return;
    setGeneratingSummary(true);
    try {
      const body = linkId ? { link_id: linkId } : { activity_id: activityId };
      const res = await authFetch(`${API}/api/link/tldr`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error("Failed to generate TLDR");
      const data = await res.json();
      setCache((prev) => ({
        ...prev,
        [cacheKey]: {
          ...(prev[cacheKey] || { loading: false }),
          loading: false,
          summary: data.summary,
          summaryContentKey: data.summary_content_key,
        },
      }));
      setShowSummary(true);
    } catch (e) {
      setCache((prev) => ({ ...prev, [cacheKey]: { ...(prev[cacheKey] || { loading: false }), loading: false, error: e instanceof Error ? e.message : String(e) } }));
    } finally {
      setGeneratingSummary(false);
    }
  };

  if (!activityId && !linkId) {
    return <p className="text-sol-base01 italic text-sm p-3">No link selected.</p>;
  }

  if (!fileData || fileData.loading) {
    return <p className="text-sol-base01 italic text-sm p-3">Loading...</p>;
  }
  if (fileData.error) {
    return <p className="text-sol-red text-sm p-3">{fileData.error}</p>;
  }
  if (fileData.content !== undefined || fileData.summary !== undefined) {
    const contentMissing = fileData.content === null || fileData.content === undefined;
    const visibleContent = showSummary && fileData.summary ? fileData.summary : (fileData.content || "");
    const header = (fileData.linkTitle || fileData.linkUrl || fileData.summaryContentKey) ? (
      <div className="px-4 pt-3 pb-2 border-b border-sol-base02 shrink-0">
        {fileData.linkTitle && (
          <button
            type="button"
            onClick={() => { navigator.clipboard.writeText(fileData.linkTitle!); }}
            className="text-sol-base1 font-semibold text-sm break-words text-left cursor-pointer bg-transparent border-0 p-0 hover:text-sol-blue"
            title={`Copy title: ${fileData.linkTitle}`}
          >
            {fileData.linkTitle}
          </button>
        )}
        {fileData.linkUrl && (
          <button
            type="button"
            onClick={() => { navigator.clipboard.writeText(fileData.linkUrl!); }}
            className="text-sol-blue hover:text-sol-cyan text-xs truncate block mt-0.5 text-left cursor-pointer bg-transparent border-0 p-0 w-full"
            title={`Copy URL: ${fileData.linkUrl}`}
          >
            {fileData.linkUrl}
          </button>
        )}
        <div className="flex gap-1 mt-2">
          {contentMissing && (
            <span className="px-1.5 py-0.5 rounded text-[0.6rem] bg-sol-orange/20 text-sol-orange" title="content_key is set but the file is not present on the EC2 VM">
              not on VM
            </span>
          )}
          {fileData.summaryContentKey && (
            <button
              onClick={() => setShowSummary((v) => !v)}
              className="px-1.5 py-0.5 rounded text-[0.6rem] bg-sol-blue/20 text-sol-blue hover:text-sol-cyan cursor-pointer"
              title={fileData.summaryContentKey}
            >
              {showSummary ? "Full Content" : "TLDR"}
            </button>
          )}
          {!fileData.summaryContentKey && (
            <button
              onClick={handleGenerateSummary}
              disabled={generatingSummary}
              className="px-1.5 py-0.5 rounded text-[0.6rem] bg-sol-base02 text-sol-base01 hover:text-sol-base0 cursor-pointer disabled:opacity-50"
            >
              {generatingSummary ? "Generating TLDR..." : "Generate TLDR"}
            </button>
          )}
        </div>
      </div>
    ) : null;
    return (
      <div className="flex flex-col h-full">
        {header}
        <div className="flex-1 min-h-0 overflow-auto">
          {contentMissing && !showSummary ? (
            <p className="text-sol-base01 italic text-sm p-3">Content key is set, but the file is not on the EC2 VM.</p>
          ) : raw ? <FileContentTable filePath={cacheKey} content={visibleContent} /> : <MarkdownPreview content={visibleContent} onExternalLinkClick={onExternalLinkClick} />}
        </div>
      </div>
    );
  }
  return null;
}

function LinksMdView({ isLoggedIn, feedId, feedLabel, onClearFeed, onPreview }: { isLoggedIn: boolean; feedId: string | null; feedLabel: string | null; onClearFeed?: () => void; onPreview: (activityId: string, contentKey: string | null) => void }) {
  return (
    <div className="flex flex-col h-full">
      {feedId ? (
        <div className="px-3 py-1.5 border-b border-sol-base02 flex items-center gap-2 bg-sol-base02/50 shrink-0">
          <span className="text-sol-base01 text-xs shrink-0">Feed:</span>
          <span className="text-sol-base0 text-sm truncate flex-1" title={feedId}>{feedLabel || feedId}</span>
          {onClearFeed && (
            <button onClick={onClearFeed} className="shrink-0 text-sol-base01 hover:text-sol-red cursor-pointer" title="Clear feed filter">
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          )}
        </div>
      ) : (
        <div className="px-3 py-2 text-sol-base01 text-sm italic shrink-0">No feed selected. Click a feed in the sidebar.</div>
      )}
      <div className="flex-1 min-h-0">
        <LinkList isLoggedIn={isLoggedIn} onPreview={(link) => onPreview(link.activity_id, link.content_key || null)} feedId={feedId} />
      </div>
    </div>
  );
}

interface EntityDetail {
  entity_id: string;
  name: string;
  type: string;
  front_matter?: Record<string, unknown> | null;
}

interface EntityNote {
  note_id: string;
  content_key: string;
  front_matter?: Record<string, unknown> | null;
}

interface EntityFeed {
  rss_feed_id: string;
  url: string;
  title?: string | null;
}

interface EntityLink {
  activity_id: string;
  url: string;
  base_url: string;
  title?: string | null;
  content_key?: string | null;
}

function entityLinkDomain(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function EntityView({ entityId, vmQuery, defaultWorkDir, onOpenFile, onPreviewLink }: { entityId: string; vmQuery: string; defaultWorkDir?: string; onOpenFile?: (path: string) => void; onPreviewLink?: (activityId: string, contentKey: string | null) => void }) {
  const [entity, setEntity] = useState<EntityDetail | null>(null);
  const [notes, setNotes] = useState<EntityNote[]>([]);
  const [feeds, setFeeds] = useState<EntityFeed[]>([]);
  const [links, setLinks] = useState<EntityLink[]>([]);
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!entityId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setContent(null);
    (async () => {
      try {
        const eRes = await authFetch(`${API}/api/entity/detail?entity_id=${encodeURIComponent(entityId)}`);
        if (!eRes.ok) throw new Error("Failed to load entity");
        const entityData: EntityDetail = await eRes.json();
        if (cancelled) return;
        setEntity(entityData);

        const noteIdsRes = await authFetch(`${API}/api/entity-note/by-entity?entity_id=${encodeURIComponent(entityId)}`);
        const noteIds: string[] = noteIdsRes.ok ? await noteIdsRes.json() : [];
        const noteDetails = await Promise.all(noteIds.map(async (nid) => {
          const r = await authFetch(`${API}/api/note/detail?note_id=${encodeURIComponent(nid)}`);
          return r.ok ? (await r.json()) as EntityNote : null;
        }));
        if (cancelled) return;
        const validNotes = noteDetails.filter((n): n is EntityNote => !!n);
        setNotes(validNotes);

        const firstKey = validNotes[0]?.content_key;
        if (firstKey) {
          const fullPath = defaultWorkDir ? `${defaultWorkDir}/${firstKey}` : firstKey;
          const cRes = await authFetch(`${API}/api/file/read?path=${encodeURIComponent(fullPath)}${vmQuery}`);
          if (cRes.ok) {
            const cData = await cRes.json();
            if (!cancelled) setContent(cData.content ?? "");
          }
        }

        const feedIdsRes = await authFetch(`${API}/api/entity-rss/by-entity?entity_id=${encodeURIComponent(entityId)}`);
        const feedIds: string[] = feedIdsRes.ok ? await feedIdsRes.json() : [];
        if (feedIds.length > 0) {
          const allFeedsRes = await authFetch(`${API}/api/rss-feed/list`);
          const allFeeds: EntityFeed[] = allFeedsRes.ok ? await allFeedsRes.json() : [];
          const feedSet = new Set(feedIds);
          if (!cancelled) setFeeds(allFeeds.filter((f) => feedSet.has(f.rss_feed_id)));
        } else {
          if (!cancelled) setFeeds([]);
        }

        const linksRes = await authFetch(`${API}/api/link/list?entity_id=${encodeURIComponent(entityId)}&limit=200`);
        const entityLinks: EntityLink[] = linksRes.ok ? await linksRes.json() : [];
        if (!cancelled) setLinks(entityLinks);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [entityId, vmQuery, defaultWorkDir]);

  if (!entityId) return <p className="text-sol-base01 italic text-sm p-3">No entity selected. Set `selectedEntityId` in localStorage.</p>;
  if (loading && !entity) return <p className="text-sol-base01 italic text-sm p-3">Loading...</p>;
  if (error) return <p className="text-sol-red text-sm p-3">{error}</p>;
  if (!entity) return null;

  const frontMatterEntries = entity.front_matter ? Object.entries(entity.front_matter) : [];

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-3 pb-2 border-b border-sol-base02 shrink-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sol-base1 font-semibold text-base break-words">{entity.name}</span>
          <span className="inline-flex items-center px-1.5 py-0.5 rounded font-mono text-[0.65rem] bg-sol-base02 text-sol-base01">{entity.type}</span>
          <span className="text-sol-base01 text-[0.65rem] font-mono">{entity.entity_id}</span>
        </div>
        {frontMatterEntries.length > 0 && (
          <div className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs">
            {frontMatterEntries.map(([k, v]) => (
              <Fragment key={k}>
                <div className="text-sol-base01">{k}</div>
                <div className="text-sol-base0 break-words">{typeof v === "string" ? v : JSON.stringify(v)}</div>
              </Fragment>
            ))}
          </div>
        )}
      </div>
      <div className="flex-1 min-h-0 overflow-auto">
        {content !== null ? (
          <MarkdownPreview content={content} />
        ) : notes.length === 0 ? (
          <p className="text-sol-base01 italic text-sm p-3">No note linked. Link via `y assoc entity {entity.entity_id} --note &lt;note_id&gt;`.</p>
        ) : (
          <p className="text-sol-base01 italic text-sm p-3">Loading linked note content...</p>
        )}
      </div>
      {(notes.length > 0 || feeds.length > 0 || links.length > 0) && (
        <div className="border-t border-sol-base02 p-3 shrink-0 text-xs space-y-2">
          {notes.length > 0 && (
            <div>
              <div className="text-sol-base01 uppercase text-[0.6rem] mb-1">Notes ({notes.length})</div>
              <ul className="space-y-0.5">
                {notes.map((n) => {
                  const fullPath = defaultWorkDir ? `${defaultWorkDir}/${n.content_key}` : n.content_key;
                  return (
                    <li key={n.note_id}>
                      <button
                        onClick={() => onOpenFile?.(fullPath)}
                        className="text-sol-blue hover:text-sol-cyan cursor-pointer truncate block text-left max-w-full"
                        title={n.content_key}
                      >
                        {n.content_key}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
          {feeds.length > 0 && (
            <div>
              <div className="text-sol-base01 uppercase text-[0.6rem] mb-1">RSS Feeds ({feeds.length})</div>
              <ul className="space-y-0.5">
                {feeds.map((f) => (
                  <li key={f.rss_feed_id} className="flex gap-2 items-baseline">
                    <span className="text-sol-base0 truncate">{f.title || f.url}</span>
                    <a href={f.url} target="_blank" rel="noreferrer" className="text-sol-blue hover:text-sol-cyan text-[0.6rem] truncate">{f.url}</a>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {links.length > 0 && (
            <div>
              <div className="text-sol-base01 uppercase text-[0.6rem] mb-1">Links ({links.length})</div>
              <ul className="space-y-0.5">
                {links.map((l) => {
                  const label = l.title || entityLinkDomain(l.base_url);
                  return (
                    <li key={l.activity_id}>
                      <button
                        onClick={() => onPreviewLink?.(l.activity_id, l.content_key ?? null)}
                        className="text-sol-blue hover:text-sol-cyan cursor-pointer truncate block text-left max-w-full"
                        title={l.url}
                      >
                        {label}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface PublicNoteCache {
  content?: string;
  loading: boolean;
  error?: string;
}

// Public note-tab viewer: tabs keyed by note `share_id`, content from the no-JWT
// `/api/note/share` endpoint, rendered via MarkdownPreview. No edit/save/import,
// no binary/raw, no special-views, no /api/file/* fetches.
function PublicFileViewer({ openFiles, activeFile, onSelectFile, onCloseFile, onReorderFiles, noteMeta }: {
  openFiles: string[];
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  onCloseFile: (path: string) => void;
  onReorderFiles: (files: string[]) => void;
  noteMeta: Record<string, { content_key: string; front_matter?: Record<string, unknown> | null }>;
}) {
  const [cache, setCache] = useState<Record<string, PublicNoteCache>>({});
  const dragIdx = useRef<number | null>(null);
  const [dropIdx, setDropIdx] = useState<number | null>(null);

  useEffect(() => {
    if (!activeFile) return;
    if (cache[activeFile] && !cache[activeFile].error) return;
    setCache((prev) => ({ ...prev, [activeFile]: { loading: true } }));
    fetch(`${API}/api/note/share?share_id=${encodeURIComponent(activeFile)}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(res.status === 401 ? "This note is password-protected" : "Failed to load note");
        const data = await res.json();
        setCache((prev) => ({ ...prev, [activeFile]: { content: data.content ?? "", loading: false } }));
      })
      .catch((e) => setCache((prev) => ({ ...prev, [activeFile]: { loading: false, error: e.message } })));
  }, [activeFile, cache]);

  const labelFor = (shareId: string) => {
    const ck = noteMeta[shareId]?.content_key || shareId;
    return ck.replace(/^.*\//, "").replace(/\.md$/, "");
  };

  if (openFiles.length === 0) {
    return <div className="h-full border-b border-sol-base02 bg-sol-base03" />;
  }

  return (
    <div className="flex flex-col h-full border-b border-sol-base02">
      {/* Tab bar */}
      <div className="flex items-center bg-sol-base02 shrink-0 overflow-x-auto">
        {openFiles.map((shareId, i) => (
          <div
            key={shareId}
            draggable
            onDragStart={(e) => { dragIdx.current = i; e.dataTransfer.effectAllowed = "move"; }}
            onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDropIdx(i); }}
            onDragLeave={() => setDropIdx((cur) => cur === i ? null : cur)}
            onDrop={(e) => {
              e.preventDefault();
              const from = dragIdx.current;
              if (from !== null && from !== i) {
                const reordered = [...openFiles];
                const [moved] = reordered.splice(from, 1);
                reordered.splice(i, 0, moved);
                onReorderFiles(reordered);
              }
              dragIdx.current = null;
              setDropIdx(null);
            }}
            onDragEnd={() => { dragIdx.current = null; setDropIdx(null); }}
            className={`flex items-center gap-1 px-3 py-1.5 text-sm cursor-pointer shrink-0 border-r border-sol-base03 ${
              shareId === activeFile ? "bg-sol-base03 text-sol-base1" : "text-sol-base01 hover:text-sol-base1"
            } ${dropIdx === i ? "border-l-2 border-l-sol-blue" : ""}`}
            onClick={() => onSelectFile(shareId)}
            title={noteMeta[shareId]?.content_key || shareId}
          >
            <span className="truncate max-w-[150px]">{labelFor(shareId)}</span>
            <button
              onClick={(e) => { e.stopPropagation(); onCloseFile(shareId); }}
              className="text-sol-base01 hover:text-sol-base1 leading-none ml-1 cursor-pointer"
            >
              &times;
            </button>
          </div>
        ))}
      </div>
      {/* Breadcrumb */}
      {activeFile && (
        <div className="flex items-center px-3 py-1 bg-sol-base03 text-xs text-sol-base01 shrink-0 border-b border-sol-base02 overflow-x-auto">
          {getBreadcrumb(noteMeta[activeFile]?.content_key || activeFile).map((part, i, arr) => (
            <span key={i} className="flex items-center shrink-0">
              {i > 0 && <span className="mx-1 text-sol-base01">&gt;</span>}
              <span className={i === arr.length - 1 ? "text-sol-base1" : ""}>{part}</span>
            </span>
          ))}
        </div>
      )}
      {/* Content - render all open notes, show/hide to preserve scroll */}
      <div className="flex-1 min-h-0 bg-sol-base03 relative">
        {openFiles.map((shareId) => {
          const isActive = shareId === activeFile;
          const fileData = cache[shareId];
          return (
            <div key={shareId} className={`absolute inset-0 overflow-auto ${isActive ? "" : "hidden"}`}>
              {!fileData || fileData.loading ? (
                <p className="text-sol-base01 italic text-sm p-3">Loading...</p>
              ) : fileData.error ? (
                <p className="text-sol-red text-sm p-3">{fileData.error}</p>
              ) : fileData.content !== undefined ? (
                <MarkdownPreview content={fileData.content} />
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function FileViewer({ openFiles, activeFile, onSelectFile, onCloseFile, onReorderFiles, vmName, workDir, defaultWorkDir, diffFiles, artifactTabs, isLoggedIn, selectedTraceId, selectedLinkId, selectedLinkLinkId, selectedLinkContentKey, selectedEntityId, selectedFeedId, selectedFeedLabel, onClearFeed, onSelectChat, onPreviewLink, onPreviewLinkFull, onExternalLinkClick, previewFile, onPinFile, onPreviewFile, pendingLines = {}, onConsumeLine, onChatListRefresh, onTraceTodoDirtyChange, mode, noteMeta }: FileViewerProps) {
  const { mutate } = useSWRConfig();
  const vmQuery = (vmName ? `&vm_name=${encodeURIComponent(vmName)}` : "") + (workDir ? `&work_dir=${encodeURIComponent(workDir)}` : "");
  const [cache, setCache] = useState<Record<string, FileCache>>({});
  const [mdPreview, setMdPreview] = useState<Record<string, boolean>>({});
  const [todoViewMode, setTodoViewMode] = useState<"table" | "kanban">(() => {
    return (localStorage.getItem("todoViewMode") as "table" | "kanban") || "table";
  });
  const [editContent, setEditContent] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const savingRef = useRef<Record<string, boolean>>({});

  const [zoom, setZoom] = useState(100);
  const [noteImported, setNoteImported] = useState<Record<string, boolean>>({});
  const blobUrls = useRef<Set<string>>(new Set());
  const dragIdx = useRef<number | null>(null);
  const [dropIdx, setDropIdx] = useState<number | null>(null);
  const activeFileName = activeFile?.replace(/^\.\//, "") ?? "";
  const isDiff = !!(activeFile && diffFiles?.has(activeFile));
  const isArtifact = !!activeFile?.startsWith("artifact:");
  const isTrace = !isDiff && !isArtifact && activeFileName === "trace.md";
  const isTodo = !isDiff && !isTrace && activeFileName.endsWith("todo.md");
  const isCalendar = !isDiff && !isTrace && activeFileName.endsWith("calendar.md");
  const isLinkPreview = !isDiff && !isTrace && activeFileName === "link.md";
  const isLinksMd = !isDiff && !isTrace && activeFileName === "links.md";
  const isEntityPreview = !isDiff && !isTrace && activeFileName === "entity.md";
  const isFinance = !isDiff && !isTrace && activeFileName.endsWith("finance.bean");
  const isEmail = !isDiff && !isTrace && activeFileName.endsWith("emails.md");
  const isDev = !isDiff && !isTrace && activeFileName.endsWith("dev.md");
  const isBot = !isDiff && !isTrace && activeFileName === "bot.md";

  // Fetch file when it becomes active and isn't cached
  useEffect(() => {
    if (mode === "public") return;
    if (!activeFile) return;
    if (isDiff || isArtifact || isTrace || isTodo || isCalendar || isLinkPreview || isLinksMd || isEntityPreview || isFinance || isEmail || isDev || isBot) return;
    if (cache[activeFile] && !cache[activeFile].error) return;

    const ext = getExt(activeFile);
    const isBinary = IMAGE_EXTS.has(ext) || PDF_EXTS.has(ext);

    setCache((prev) => ({ ...prev, [activeFile]: { loading: true } }));

    if (isBinary) {
      authFetch(`${API}/api/file/raw?path=${encodeURIComponent(activeFile)}${vmQuery}`)
        .then(async (res) => {
          if (!res.ok) throw new Error("Failed to read file");
          const blob = await res.blob();
          const url = URL.createObjectURL(blob);
          blobUrls.current.add(url);
          setCache((prev) => ({ ...prev, [activeFile]: { blobUrl: url, loading: false } }));
        })
        .catch((e) => setCache((prev) => ({ ...prev, [activeFile]: { loading: false, error: e.message } })));
    } else {
      authFetch(`${API}/api/file/read?path=${encodeURIComponent(activeFile)}${vmQuery}`)
        .then(async (res) => {
          if (!res.ok) throw new Error("Failed to read file");
          const data = await res.json();
          setCache((prev) => ({ ...prev, [activeFile]: { content: data.content, loading: false } }));
          // Auto-switch to raw (edit) mode for empty files
          if (!data.content) {
            setMdPreview((prev) => ({ ...prev, [activeFile]: false }));
          }
        })
        .catch((e) => setCache((prev) => ({ ...prev, [activeFile]: { loading: false, error: e.message } })));
    }
  }, [activeFile, cache, isArtifact, isBot, isCalendar, isDev, isDiff, isEmail, isEntityPreview, isFinance, isLinkPreview, isLinksMd, isTodo, isTrace, vmQuery, mode]);

  // Clean up blob URLs, cache, and editContent for closed files
  useEffect(() => {
    setCache((prev) => {
      const next: Record<string, FileCache> = {};
      for (const f of openFiles) {
        if (prev[f]) next[f] = prev[f];
      }
      for (const [path, entry] of Object.entries(prev)) {
        if (!openFiles.includes(path) && entry.blobUrl) {
          URL.revokeObjectURL(entry.blobUrl);
          blobUrls.current.delete(entry.blobUrl);
        }
      }
      return next;
    });
    setEditContent((prev) => {
      const next: Record<string, string> = {};
      for (const f of openFiles) {
        if (prev[f] !== undefined) next[f] = prev[f];
      }
      return next;
    });
  }, [openFiles]);

  useEffect(() => {
    return () => {
      blobUrls.current.forEach((url) => URL.revokeObjectURL(url));
    };
  }, []);

  // Reset zoom when switching files (null = auto fit)
  useEffect(() => { setZoom(0); }, [activeFile]);

  const handleRefresh = useCallback(() => {
    if (!activeFile) return;
    if (isTrace) {
      mutate((key) => typeof key === "string" && key.includes("/api/trace/"));
      return;
    }
    if (isTodo) {
      mutate((key) => typeof key === "string" && key.includes("/api/todo/"));
      return;
    }
    if (isCalendar) {
      mutate((key) => typeof key === "string" && key.includes("/api/calendar/"));
      return;
    }
    if (isLinkPreview) {
      // Clear cache so it re-fetches (both activity-keyed and link-keyed entries)
      setCache((prev) => {
        const next = { ...prev };
        delete next[activeFile];
        if (selectedLinkId) delete next[`link:activity:${selectedLinkId}`];
        if (selectedLinkLinkId) delete next[`link:link:${selectedLinkLinkId}`];
        return next;
      });
      return;
    }
    if (isLinksMd) {
      mutate((key) => typeof key === "string" && key.includes("/api/link/list"));
      return;
    }
    if (isEntityPreview) {
      mutate((key) => typeof key === "string" && (key.includes("/api/entity/") || key.includes("/api/entity-note/") || key.includes("/api/entity-rss/")));
      return;
    }
    if (isFinance) {
      mutate((key) => typeof key === "string" && key.includes("/api/finance/"));
      return;
    }
    if (isEmail) {
      mutate((key) => typeof key === "string" && key.includes("/api/email/"));
      return;
    }
    if (isDev) {
      mutate((key) => typeof key === "string" && key.includes("/api/dev-worktree/"));
      return;
    }
    if (isBot) {
      mutate((key) => typeof key === "string" && key.includes("/api/bot/list"));
      return;
    }
    // Clear cache entry so useEffect re-fetches
    setCache((prev) => {
      const next = { ...prev };
      if (next[activeFile]?.blobUrl) {
        URL.revokeObjectURL(next[activeFile].blobUrl!);
        blobUrls.current.delete(next[activeFile].blobUrl!);
      }
      delete next[activeFile];
      return next;
    });
  }, [activeFile, isTodo, isCalendar, isLinkPreview, isLinksMd, isEntityPreview, isFinance, isEmail, isDev, isBot, mutate, selectedLinkId, selectedLinkLinkId]);

  const isDirty = useCallback((path: string) => {
    return editContent[path] !== undefined && editContent[path] !== (cache[path]?.content ?? "");
  }, [editContent, cache]);

  const handleSave = useCallback(async (path: string) => {
    if (savingRef.current[path]) return;
    if (!isDirty(path)) return;
    const snapshot = editContent[path];
    savingRef.current[path] = true;
    setSaving((prev) => ({ ...prev, [path]: true }));
    try {
      const res = await authFetch(`${API}/api/file/write${vmQuery ? "?" + vmQuery.slice(1) : ""}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, content: snapshot }),
      });
      if (!res.ok) throw new Error("Failed to save");
      setCache((prev) => ({ ...prev, [path]: { ...prev[path], content: snapshot, loading: false } }));
      setEditContent((prev) => {
        if (prev[path] !== snapshot) return prev;
        const next = { ...prev };
        delete next[path];
        return next;
      });
    } catch (e: any) {
      alert(`Save failed: ${e.message}`);
    } finally {
      savingRef.current[path] = false;
      setSaving((prev) => ({ ...prev, [path]: false }));
    }
  }, [isDirty, editContent, vmQuery]);

  if (mode === "public") {
    return (
      <PublicFileViewer
        openFiles={openFiles}
        activeFile={activeFile}
        onSelectFile={onSelectFile}
        onCloseFile={onCloseFile}
        onReorderFiles={onReorderFiles}
        noteMeta={noteMeta || {}}
      />
    );
  }

  if (openFiles.length === 0) {
    return <div className="h-full border-b border-sol-base02 bg-sol-base03" />;
  }

  return (
    <div className="flex flex-col h-full border-b border-sol-base02">
      {/* Tab bar */}
      <div className="flex items-center bg-sol-base02 shrink-0 overflow-x-auto">
        {openFiles.map((filePath, i) => (
          <div
            key={filePath}
            draggable
            onDragStart={(e) => {
              dragIdx.current = i;
              e.dataTransfer.effectAllowed = "move";
            }}
            onDragOver={(e) => {
              e.preventDefault();
              e.dataTransfer.dropEffect = "move";
              setDropIdx(i);
            }}
            onDragLeave={() => setDropIdx((cur) => cur === i ? null : cur)}
            onDrop={(e) => {
              e.preventDefault();
              const from = dragIdx.current;
              if (from !== null && from !== i) {
                const reordered = [...openFiles];
                const [moved] = reordered.splice(from, 1);
                reordered.splice(i, 0, moved);
                onReorderFiles(reordered);
              }
              dragIdx.current = null;
              setDropIdx(null);
            }}
            onDragEnd={() => { dragIdx.current = null; setDropIdx(null); }}
            className={`flex items-center gap-1 px-3 py-1.5 text-sm cursor-pointer shrink-0 border-r border-sol-base03 ${
              filePath === activeFile
                ? "bg-sol-base03 text-sol-base1"
                : "text-sol-base01 hover:text-sol-base1"
            } ${dropIdx === i ? "border-l-2 border-l-sol-blue" : ""}`}
            onClick={() => onSelectFile(filePath)}
            onDoubleClick={() => { if (filePath === previewFile && onPinFile) onPinFile(filePath); }}
            title={filePath}
          >
            {isDirty(filePath) && <span className="w-2 h-2 rounded-full bg-sol-base0 shrink-0" />}
            <span className={`truncate max-w-[150px] ${filePath === previewFile ? "italic" : ""}`}>{filePath.startsWith("artifact:") ? artifactLabel(filePath, artifactTabs) : filePath.startsWith("diff:") ? `${getFileName(filePath.slice(5))} (diff)` : getFileName(filePath)}</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onCloseFile(filePath);
              }}
              className="text-sol-base01 hover:text-sol-base1 leading-none ml-1 cursor-pointer"
            >
              &times;
            </button>
          </div>
        ))}
      </div>
      {/* Breadcrumb */}
      {activeFile && (
        <div className="flex items-center px-3 py-1 bg-sol-base03 text-xs text-sol-base01 shrink-0 border-b border-sol-base02 overflow-x-auto">
          {isDiff && <span className="text-sol-yellow font-semibold mr-1 shrink-0">DIFF</span>}
          {getBreadcrumb(isArtifact ? artifactLabel(activeFile, artifactTabs) : isLinkPreview && selectedLinkContentKey ? (defaultWorkDir ? `${defaultWorkDir}/${selectedLinkContentKey}` : selectedLinkContentKey) : activeFile.replace(/^diff:/, "")).map((part, i, arr) => (
            <span key={i} className="flex items-center shrink-0">
              {i > 0 && <span className="mx-1 text-sol-base01">&gt;</span>}
              <span className={i === arr.length - 1 ? "text-sol-base1" : ""}>{part}</span>
            </span>
          ))}
          {isTodo && (
            <button
              onClick={() => setTodoViewMode((v) => { const next = v === "table" ? "kanban" : "table"; localStorage.setItem("todoViewMode", next); return next; })}
              className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-2 shrink-0 text-xs"
              title={todoViewMode === "table" ? "Switch to kanban" : "Switch to table"}
            >
              {todoViewMode === "table" ? "Kanban" : "Table"}
            </button>
          )}
          {isLinkPreview && (
            <button
              onClick={() => setMdPreview((prev) => ({ ...prev, [activeFile]: prev[activeFile] === false }))}
              className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-2 shrink-0 text-xs"
              title={mdPreview[activeFile] !== false ? "Show raw" : "Show preview"}
            >
              {mdPreview[activeFile] !== false ? "Raw" : "Preview"}
            </button>
          )}
          {isLinkPreview && (selectedLinkId || selectedLinkLinkId) && (() => {
            const linkCacheKey = selectedLinkId
              ? `link:activity:${selectedLinkId}`
              : selectedLinkLinkId
              ? `link:link:${selectedLinkLinkId}`
              : "";
            const linkContent = linkCacheKey ? cache[linkCacheKey]?.content : undefined;
            if (!linkContent) return null;
            const nameSource = selectedLinkContentKey
              ? getFileName(selectedLinkContentKey)
              : `link-${selectedLinkId || selectedLinkLinkId}`;
            return (
              <button
                onClick={() => downloadAsMarkdown(nameSource, linkContent)}
                className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-2 shrink-0"
                title="Download as Markdown"
              >
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="7 10 12 15 17 10"/>
                  <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
              </button>
            );
          })()}
          {(activeFileName.startsWith("pages/") || activeFileName.includes("/pages/")) && (
            <button
              onClick={async () => {
                const path = activeFileName;
                try {
                  const res = await authFetch(`${API}/api/note/import`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ content_key: path }),
                  });
                  if (res.ok) {
                    setNoteImported((prev) => ({ ...prev, [activeFile!]: true }));
                    setTimeout(() => setNoteImported((prev) => ({ ...prev, [activeFile!]: false })), 2000);
                  }
                } catch {}
              }}
              className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-2 shrink-0 text-xs"
              title="Import Note"
            >
              {noteImported[activeFile] ? "Imported!" : (
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="12" y1="18" x2="12" y2="12" />
                  <line x1="9" y1="15" x2="15" y2="15" />
                </svg>
              )}
            </button>
          )}
          {getExt(activeFile) === "md" && !isTodo && !isCalendar && !isEmail && !isTrace && !isLinkPreview && !isEntityPreview && (
            <button
              onClick={() => setMdPreview((prev) => ({ ...prev, [activeFile]: prev[activeFile] === false }))}
              className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-2 shrink-0 text-xs"
              title={mdPreview[activeFile] !== false ? "Show raw" : "Show preview"}
            >
              {mdPreview[activeFile] !== false ? "Raw" : "Preview"}
            </button>
          )}
          {getExt(activeFile) === "md" && !isTodo && !isCalendar && !isEmail && !isTrace && !isLinkPreview && !isEntityPreview && !isDiff && (() => {
            const content = editContent[activeFile] ?? cache[activeFile]?.content;
            if (content === undefined) return null;
            return (
              <button
                onClick={() => downloadAsMarkdown(getFileName(activeFile), content)}
                className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-2 shrink-0"
                title="Download as Markdown"
              >
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="7 10 12 15 17 10"/>
                  <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
              </button>
            );
          })()}
          {isDirty(activeFile) && (
            <button
              onClick={() => handleSave(activeFile)}
              disabled={saving[activeFile]}
              className="text-sol-green hover:text-sol-base1 cursor-pointer p-0.5 ml-2 shrink-0 text-xs font-semibold disabled:opacity-50"
              title="Save file"
            >
              {saving[activeFile] ? "Saving..." : "Save"}
            </button>
          )}
          {!isArtifact && <button
            onClick={handleRefresh}
            className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-2 shrink-0"
            title="Refresh file"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8 1a7 7 0 0 1 7 7h-1.5A5.5 5.5 0 0 0 8 2.5V5L4.5 2 8 -1v2zm0 14a7 7 0 0 1-7-7h1.5A5.5 5.5 0 0 0 8 13.5V11l3.5 3L8 17v-2z" />
            </svg>
          </button>}
          {!isArtifact && <button
            onClick={() => {
              const pathToCopy = isLinkPreview && selectedLinkContentKey && defaultWorkDir
                ? `${defaultWorkDir}/${selectedLinkContentKey}`
                : activeFile.replace(/^\.\//, "");
              navigator.clipboard.writeText(pathToCopy);
            }}
            className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-1 shrink-0"
            title="Copy path"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
              <path d="M4 2a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V2zm2-1a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V2a1 1 0 0 0-1-1H6z" />
              <path d="M2 4a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-1h1v1a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h1v1H2z" />
            </svg>
          </button>}
        </div>
      )}
      {/* Content - render all open files, show/hide to preserve scroll */}
      <div className="flex-1 min-h-0 bg-sol-base03 relative">
        {openFiles.map((filePath) => {
          const fileDiff = !!(diffFiles?.has(filePath));
          const fileArtifact = filePath.startsWith("artifact:");
          const fileName = filePath.replace(/^\.\//, "").replace(/^diff:/, "");
          const fileTrace = !fileDiff && !fileArtifact && fileName === "trace.md";
          const fileTodo = !fileDiff && !fileTrace && fileName.endsWith("todo.md");
          const fileCalendar = !fileDiff && !fileTrace && fileName.endsWith("calendar.md");
          const fileLinkPreview = !fileDiff && !fileTrace && fileName === "link.md";
          const fileLinksMd = !fileDiff && !fileTrace && fileName === "links.md";
          const fileEntityPreview = !fileDiff && !fileTrace && fileName === "entity.md";
          const fileFinance = !fileDiff && !fileTrace && fileName.endsWith("finance.bean");
          const fileEmail = !fileDiff && !fileTrace && fileName.endsWith("emails.md");
          const fileDev = !fileDiff && !fileTrace && fileName.endsWith("dev.md");
          const fileBot = !fileDiff && !fileTrace && fileName === "bot.md";
          const isActive = filePath === activeFile;
          const fileData = cache[filePath];
          const fileExt = getExt(fileName);
          const fileIsImage = IMAGE_EXTS.has(fileExt);
          const fileIsPdf = PDF_EXTS.has(fileExt);

          return (
            <div
              key={filePath}
              className={`absolute inset-0 ${fileArtifact || fileTodo || fileCalendar || fileFinance || fileEmail || fileDev || fileBot || fileDiff || fileTrace || fileLinksMd || fileEntityPreview ? "overflow-hidden" : "overflow-auto"} ${isActive ? "" : "hidden"}`}
            >
              {fileDiff ? (
                <DiffViewer filePath={fileName} vmName={vmName} workDir={workDir} />
              ) : fileArtifact && artifactTabs?.[filePath] ? (
                <ArtifactView
                  type={artifactTabs[filePath].type}
                  spec={artifactTabs[filePath].spec}
                  mode={(mdPreview[filePath] !== false ? "preview" : "raw") as ArtifactMode}
                  onModeChange={(mode) => setMdPreview((prev) => ({ ...prev, [filePath]: mode === "preview" }))}
                  variant="tab"
                />
              ) : fileTrace ? (
                <TraceView isLoggedIn={!!isLoggedIn} selectedTraceId={selectedTraceId || ""} defaultWorkDir={defaultWorkDir} onSelectChat={onSelectChat} onPreviewLink={onPreviewLink ? (activityId: string) => onPreviewLink(activityId) : undefined} onOpenFile={onPreviewFile} onTraceTodoDirtyChange={onTraceTodoDirtyChange} />
              ) : fileTodo ? (
                <TodoViewer viewMode={todoViewMode} onChatListRefresh={onChatListRefresh} />
              ) : fileCalendar ? (
                <CalendarViewer onOpenFile={onSelectFile} />
              ) : fileLinkPreview ? (
                <LinkContentView activityId={selectedLinkId || null} linkId={selectedLinkLinkId || null} cache={cache} setCache={setCache} raw={mdPreview[filePath] === false} onExternalLinkClick={onExternalLinkClick} />
              ) : fileLinksMd ? (
                <LinksMdView
                  isLoggedIn={!!isLoggedIn}
                  feedId={selectedFeedId || null}
                  feedLabel={selectedFeedLabel || null}
                  onClearFeed={onClearFeed}
                  onPreview={(activityId, contentKey) => {
                    if (onPreviewLinkFull) onPreviewLinkFull(activityId, contentKey);
                    else if (onPreviewLink) onPreviewLink(activityId);
                  }}
                />
              ) : fileEntityPreview ? (
                <EntityView
                  entityId={selectedEntityId || ""}
                  vmQuery={vmQuery}
                  defaultWorkDir={defaultWorkDir}
                  onOpenFile={onPreviewFile}
                  onPreviewLink={(activityId, contentKey) => {
                    if (onPreviewLinkFull) onPreviewLinkFull(activityId, contentKey);
                    else if (onPreviewLink) onPreviewLink(activityId);
                  }}
                />
              ) : fileFinance ? (
                <FinanceViewer vmName={vmName} />
              ) : fileEmail ? (
                <EmailViewer />
              ) : fileDev ? (
                <DevViewer />
              ) : fileBot ? (
                <BotViewer />
              ) : !fileData || fileData.loading ? (
                <p className="text-sol-base01 italic text-sm p-3">Loading...</p>
              ) : fileData.error ? (
                <p className="text-sol-red text-sm p-3">{fileData.error}</p>
              ) : fileIsImage && fileData.blobUrl ? (
                <div className="flex flex-col h-full">
                  <div className="flex-1 overflow-auto p-3">
                    <img
                      src={fileData.blobUrl}
                      alt={filePath}
                      style={zoom ? { width: `${zoom}%`, maxWidth: "none" } : { maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }}
                      onWheel={(e) => {
                        if (e.ctrlKey || e.metaKey) {
                          e.preventDefault();
                          setZoom((z) => Math.min(500, Math.max(10, (z || 100) + (e.deltaY < 0 ? 10 : -10))));
                        }
                      }}
                    />
                  </div>
                </div>
              ) : fileIsPdf && fileData.blobUrl ? (
                <iframe src={fileData.blobUrl} className="w-full h-full border-0" title={filePath} />
              ) : fileData.content !== undefined ? (
                getExt(filePath) === "md" && mdPreview[filePath] !== false ? (
                  <MarkdownPreview content={editContent[filePath] ?? fileData.content} currentFilePath={filePath} onOpenFile={onPreviewFile} onExternalLinkClick={onExternalLinkClick} />
                ) : (
                  <div className="h-full overflow-hidden bg-sol-base03" data-editor="true">
                    <CodeEditor
                      filePath={filePath}
                      value={editContent[filePath] ?? fileData.content ?? ""}
                      onChange={(v) => setEditContent((prev) => ({ ...prev, [filePath]: v }))}
                      onSave={handleSave}
                      initialLine={pendingLines[filePath]}
                      onInitialLineApplied={() => onConsumeLine?.(filePath)}
                    />
                  </div>
                )
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
