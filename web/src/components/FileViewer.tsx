import { useEffect, useState, useRef, useMemo, useCallback } from "react";
import { API, authFetch } from "../api";
import hljs from "highlight.js";
import "highlight.js/styles/base16/solarized-dark.min.css";
import TodoViewer from "./TodoViewer";
import CalendarViewer from "./CalendarViewer";


interface FileViewerProps {
  openFiles: string[];
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  onCloseFile: (path: string) => void;
  onReorderFiles: (files: string[]) => void;
  onLocateFile?: (path: string) => void;
  vmName?: string | null;
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

export default function FileViewer({ openFiles, activeFile, onSelectFile, onCloseFile, onReorderFiles, onLocateFile, vmName }: FileViewerProps) {
  const vmQuery = vmName ? `&vm_name=${encodeURIComponent(vmName)}` : "";
  const [cache, setCache] = useState<Record<string, FileCache>>({});
  const [zoom, setZoom] = useState(100);
  const blobUrls = useRef<Set<string>>(new Set());
  const dragIdx = useRef<number | null>(null);
  const [dropIdx, setDropIdx] = useState<number | null>(null);
  const activeFileName = activeFile?.replace(/^\.\//, "") ?? "";
  const isTodo = activeFileName === "todo.md";
  const isCalendar = activeFileName === "calendar.md";

  // Fetch file when it becomes active and isn't cached
  useEffect(() => {
    if (!activeFile) return;
    if (isTodo || isCalendar) return;
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
  }, [activeFile]);

  const activeData = activeFile ? cache[activeFile] : undefined;
  const ext = activeFile ? getExt(activeFile) : "";
  const isImage = IMAGE_EXTS.has(ext);
  const isPdf = PDF_EXTS.has(ext);

  // Syntax highlight
  const highlightedHtml = useMemo(() => {
    if (!activeData?.content || !activeFile) return null;
    const lang = getExt(activeFile);
    try {
      if (lang && hljs.getLanguage(lang)) {
        return hljs.highlight(activeData.content, { language: lang }).value;
      }
      return hljs.highlightAuto(activeData.content).value;
    } catch {
      return null;
    }
  }, [activeData?.content, activeFile]);

  const lineCount = activeData?.content ? activeData.content.split("\n").length : 0;

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
            <span className="truncate max-w-[150px]">{getFileName(filePath)}</span>
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
          {getBreadcrumb(activeFile).map((part, i, arr) => (
            <span key={i} className="flex items-center shrink-0">
              {i > 0 && <span className="mx-1 text-sol-base01">&gt;</span>}
              <span className={i === arr.length - 1 ? "text-sol-base1" : ""}>{part}</span>
            </span>
          ))}
          <button
            onClick={handleRefresh}
            className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-2 shrink-0"
            title="Refresh file"
          >
            <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8 1a7 7 0 0 1 7 7h-1.5A5.5 5.5 0 0 0 8 2.5V5L4.5 2 8 -1v2zm0 14a7 7 0 0 1-7-7h1.5A5.5 5.5 0 0 0 8 13.5V11l3.5 3L8 17v-2z" />
            </svg>
          </button>
          {onLocateFile && (
            <button
              onClick={() => onLocateFile(activeFile)}
              className="text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-1 shrink-0"
              title="Locate file in tree"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
                <path d="M14 1H2a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V2a1 1 0 0 0-1-1zM2 0a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V2a2 2 0 0 0-2-2H2z" />
                <circle cx="8" cy="7" r="2.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
                <line x1="10" y1="9" x2="13" y2="12" stroke="currentColor" strokeWidth="1.5" />
              </svg>
            </button>
          )}
        </div>
      )}
      {/* Content */}
      <div className={`flex-1 min-h-0 bg-sol-base03 ${isTodo || isCalendar ? "overflow-hidden" : "overflow-auto"}`}>
        {isTodo ? (
          <TodoViewer />
        ) : isCalendar ? (
          <CalendarViewer onOpenFile={onSelectFile} />
        ) : !activeData || activeData.loading ? (
          <p className="text-sol-base01 italic text-sm p-3">Loading...</p>
        ) : activeData.error ? (
          <p className="text-sol-red text-sm p-3">{activeData.error}</p>
        ) : isImage && activeData.blobUrl ? (
          <div className="flex flex-col h-full">
            <div className="flex-1 overflow-auto p-3">
              <img
                src={activeData.blobUrl}
                alt={activeFile!}
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
        ) : isPdf && activeData.blobUrl ? (
          <iframe src={activeData.blobUrl} className="w-full h-full border-0" title={activeFile!} />
        ) : activeData.content !== undefined ? (
          <table className="text-sm font-mono leading-relaxed w-full border-collapse">
            <tbody>
              {(activeData.content).split("\n").map((line, i) => (
                <tr key={i}>
                  <td className="select-none text-right pr-3 pl-2 text-sol-base01 border-r border-sol-base02 align-top bg-sol-base03 sticky left-0 w-[1%]">
                    {i + 1}
                  </td>
                  {highlightedHtml ? (
                    <td className="pl-4 pr-3 whitespace-pre-wrap break-all hljs" dangerouslySetInnerHTML={{ __html: highlightedHtml.split("\n")[i] ?? "" }} />
                  ) : (
                    <td className="pl-4 pr-3 text-sol-base0 whitespace-pre-wrap break-all">
                      {line}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </div>
    </div>
  );
}
