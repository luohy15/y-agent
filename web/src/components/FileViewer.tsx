import { useEffect, useState, useRef, useMemo, useCallback } from "react";
import { useSWRConfig } from "swr";
import { API, authFetch } from "../api";
import hljs from "highlight.js";
import "highlight.js/styles/base16/solarized-dark.min.css";
import TodoViewer from "./TodoViewer";
import CalendarViewer from "./CalendarViewer";
import LinkViewer from "./LinkViewer";
import FinanceViewer from "./FinanceViewer";
import EmailViewer from "./EmailViewer";
import DevViewer from "./DevViewer";
import DiffViewer from "./DiffViewer";
import TraceView from "./TraceView";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";


interface FileViewerProps {
  openFiles: string[];
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  onCloseFile: (path: string) => void;
  onReorderFiles: (files: string[]) => void;
  vmName?: string | null;
  workDir?: string;
  diffFiles?: Set<string>;
  isLoggedIn?: boolean;
  selectedTraceId?: string | null;
  onSelectChat?: (chatId: string) => void;
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

function getBreadcrumb(path: string): string[] {
  return path.replace(/^\.\//, "").split("/").filter(Boolean);
}

interface FileCache {
  content?: string;
  blobUrl?: string;
  loading: boolean;
  error?: string;
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

  const lines = content.split("\n");
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

function MarkdownToc({ headings, onSelect }: { headings: { text: string; id: string }[]; onSelect?: () => void }) {
  return (
    <ul className="space-y-1">
      {headings.map((h) => (
        <li key={h.id}>
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

function MarkdownPreview({ content }: { content: string }) {
  const [tocOpen, setTocOpen] = useState(false);
  const headings = useMemo(() => {
    const lines = content.split("\n");
    const result: { text: string; id: string }[] = [];
    for (const line of lines) {
      const m = line.match(/^## (.+)/);
      if (m) {
        const text = m[1].trim();
        const id = text.toLowerCase().replace(/[\s\p{P}]+/gu, "-").replace(/(^-|-$)/g, "");
        result.push({ text, id });
      }
    }
    return result;
  }, [content]);

  return (
    <div className="flex h-full">
      <div className="flex-1 min-w-0 overflow-auto p-4 prose prose-invert prose-sm max-w-none text-sol-base0 break-words [&_pre]:overflow-x-auto [&_table]:overflow-x-auto [&_img]:max-w-full">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            h2: ({ children, ...props }) => {
              const text = String(children).trim();
              const id = text.toLowerCase().replace(/[\s\p{P}]+/gu, "-").replace(/(^-|-$)/g, "");
              return <h2 id={id} {...props}>{children}</h2>;
            },
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
      {/* Desktop: sidebar TOC */}
      {headings.length > 0 && (
        <nav className="hidden md:block w-48 shrink-0 overflow-y-auto border-l border-sol-base02 p-3">
          <div className="text-xs text-sol-base01 mb-2">Contents</div>
          <MarkdownToc headings={headings} />
        </nav>
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

export default function FileViewer({ openFiles, activeFile, onSelectFile, onCloseFile, onReorderFiles, vmName, workDir, diffFiles, isLoggedIn, selectedTraceId, onSelectChat }: FileViewerProps) {
  const { mutate } = useSWRConfig();
  const vmQuery = (vmName ? `&vm_name=${encodeURIComponent(vmName)}` : "") + (workDir ? `&work_dir=${encodeURIComponent(workDir)}` : "");
  const [cache, setCache] = useState<Record<string, FileCache>>({});
  const [mdPreview, setMdPreview] = useState<Record<string, boolean>>({});
  const [todoViewMode, setTodoViewMode] = useState<"table" | "kanban">(() => {
    return (localStorage.getItem("todoViewMode") as "table" | "kanban") || "table";
  });
  const [zoom, setZoom] = useState(100);
  const blobUrls = useRef<Set<string>>(new Set());
  const dragIdx = useRef<number | null>(null);
  const [dropIdx, setDropIdx] = useState<number | null>(null);
  const activeFileName = activeFile?.replace(/^\.\//, "") ?? "";
  const isDiff = !!(activeFile && diffFiles?.has(activeFile));
  const isTrace = !isDiff && activeFileName === "trace.md";
  const isTodo = !isDiff && !isTrace && activeFileName.endsWith("todo.md");
  const isCalendar = !isDiff && !isTrace && activeFileName.endsWith("calendar.md");
  const isLink = !isDiff && !isTrace && activeFileName.endsWith("links.md");
  const isFinance = !isDiff && !isTrace && activeFileName.endsWith("finance.bean");
  const isEmail = !isDiff && !isTrace && activeFileName.endsWith("emails.md");
  const isDev = !isDiff && !isTrace && activeFileName.endsWith("dev.md");

  // Fetch file when it becomes active and isn't cached
  useEffect(() => {
    if (!activeFile) return;
    if (isDiff || isTrace || isTodo || isCalendar || isLink || isFinance || isEmail || isDev) return;
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
        })
        .catch((e) => setCache((prev) => ({ ...prev, [activeFile]: { loading: false, error: e.message } })));
    }
  }, [activeFile, cache, vmQuery]);

  // Clean up blob URLs and cache for closed files
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
    if (isTodo) {
      mutate((key) => typeof key === "string" && key.includes("/api/todo/"));
      return;
    }
    if (isCalendar) {
      mutate((key) => typeof key === "string" && key.includes("/api/calendar/"));
      return;
    }
    if (isLink) {
      mutate((key) => typeof key === "string" && key.includes("/api/link/"));
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
  }, [activeFile, isTodo, isCalendar, isLink, isFinance, isEmail, isDev, mutate]);


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
            title={filePath}
          >
            <span className="truncate max-w-[150px]">{filePath.startsWith("diff:") ? `${getFileName(filePath.slice(5))} (diff)` : getFileName(filePath)}</span>
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
          {getBreadcrumb(activeFile.replace(/^diff:/, "")).map((part, i, arr) => (
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
          {getExt(activeFile) === "md" && !isTodo && !isCalendar && !isLink && !isEmail && (
            <button
              onClick={() => setMdPreview((prev) => ({ ...prev, [activeFile]: prev[activeFile] === false }))}
              className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-2 shrink-0 text-xs"
              title={mdPreview[activeFile] !== false ? "Show raw" : "Show preview"}
            >
              {mdPreview[activeFile] !== false ? "Raw" : "Preview"}
            </button>
          )}
          <button
            onClick={handleRefresh}
            className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-2 shrink-0"
            title="Refresh file"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8 1a7 7 0 0 1 7 7h-1.5A5.5 5.5 0 0 0 8 2.5V5L4.5 2 8 -1v2zm0 14a7 7 0 0 1-7-7h1.5A5.5 5.5 0 0 0 8 13.5V11l3.5 3L8 17v-2z" />
            </svg>
          </button>
          <button
            onClick={() => {
              navigator.clipboard.writeText(activeFile.replace(/^\.\//, ""));
            }}
            className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-1 shrink-0"
            title="Copy path"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
              <path d="M4 2a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V2zm2-1a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V2a1 1 0 0 0-1-1H6z" />
              <path d="M2 4a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-1h1v1a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h1v1H2z" />
            </svg>
          </button>
        </div>
      )}
      {/* Content - render all open files, show/hide to preserve scroll */}
      <div className="flex-1 min-h-0 bg-sol-base03 relative">
        {openFiles.map((filePath) => {
          const fileDiff = !!(diffFiles?.has(filePath));
          const fileName = filePath.replace(/^\.\//, "").replace(/^diff:/, "");
          const fileTrace = !fileDiff && fileName === "trace.md";
          const fileTodo = !fileDiff && !fileTrace && fileName.endsWith("todo.md");
          const fileCalendar = !fileDiff && !fileTrace && fileName.endsWith("calendar.md");
          const fileLink = !fileDiff && !fileTrace && fileName.endsWith("links.md");
          const fileFinance = !fileDiff && !fileTrace && fileName.endsWith("finance.bean");
          const fileEmail = !fileDiff && !fileTrace && fileName.endsWith("emails.md");
          const fileDev = !fileDiff && !fileTrace && fileName.endsWith("dev.md");
          const isActive = filePath === activeFile;
          const fileData = cache[filePath];
          const fileExt = getExt(fileName);
          const fileIsImage = IMAGE_EXTS.has(fileExt);
          const fileIsPdf = PDF_EXTS.has(fileExt);

          return (
            <div
              key={filePath}
              className={`absolute inset-0 ${fileTodo || fileCalendar || fileLink || fileFinance || fileEmail || fileDev || fileDiff || fileTrace ? "overflow-hidden" : "overflow-auto"} ${isActive ? "" : "hidden"}`}
            >
              {fileDiff ? (
                <DiffViewer filePath={fileName} vmName={vmName} workDir={workDir} />
              ) : fileTrace ? (
                <TraceView isLoggedIn={!!isLoggedIn} selectedTraceId={selectedTraceId || ""} onSelectChat={onSelectChat} />
              ) : fileTodo ? (
                <TodoViewer viewMode={todoViewMode} />
              ) : fileCalendar ? (
                <CalendarViewer onOpenFile={onSelectFile} />
              ) : fileLink ? (
                <LinkViewer />
              ) : fileFinance ? (
                <FinanceViewer vmName={vmName} />
              ) : fileEmail ? (
                <EmailViewer />
              ) : fileDev ? (
                <DevViewer />
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
                  <MarkdownPreview content={fileData.content} />
                ) : (
                  <FileContentTable filePath={filePath} content={fileData.content} />
                )
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
