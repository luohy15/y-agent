import { useEffect, useState, useRef, useMemo } from "react";
import { API, authFetch } from "../api";
import hljs from "highlight.js";
import "highlight.js/styles/base16/solarized-dark.min.css";
import TodoViewer from "./TodoViewer";


interface FileViewerProps {
  openFiles: string[];
  activeFile: string | null;
  onSelectFile: (path: string) => void;
  onCloseFile: (path: string) => void;
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

export default function FileViewer({ openFiles, activeFile, onSelectFile, onCloseFile }: FileViewerProps) {
  const [cache, setCache] = useState<Record<string, FileCache>>({});
  const [zoom, setZoom] = useState(100);
  const blobUrls = useRef<Set<string>>(new Set());
  const isTodo = activeFile?.endsWith("todo/todo.md") ?? false;

  // Fetch file when it becomes active and isn't cached
  useEffect(() => {
    if (!activeFile) return;
    if (isTodo) return;
    if (cache[activeFile] && !cache[activeFile].error) return;

    const ext = getExt(activeFile);
    const isBinary = IMAGE_EXTS.has(ext) || PDF_EXTS.has(ext);

    setCache((prev) => ({ ...prev, [activeFile]: { loading: true } }));

    if (isBinary) {
      authFetch(`${API}/api/file/raw?path=${encodeURIComponent(activeFile)}`)
        .then(async (res) => {
          if (!res.ok) throw new Error("Failed to read file");
          const blob = await res.blob();
          const url = URL.createObjectURL(blob);
          blobUrls.current.add(url);
          setCache((prev) => ({ ...prev, [activeFile]: { blobUrl: url, loading: false } }));
        })
        .catch((e) => setCache((prev) => ({ ...prev, [activeFile]: { loading: false, error: e.message } })));
    } else {
      authFetch(`${API}/api/file/read?path=${encodeURIComponent(activeFile)}`)
        .then(async (res) => {
          if (!res.ok) throw new Error("Failed to read file");
          const data = await res.json();
          setCache((prev) => ({ ...prev, [activeFile]: { content: data.content, loading: false } }));
        })
        .catch((e) => setCache((prev) => ({ ...prev, [activeFile]: { loading: false, error: e.message } })));
    }
  }, [activeFile, cache]);

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
        {openFiles.map((filePath) => (
          <div
            key={filePath}
            className={`flex items-center gap-1 px-3 py-1.5 text-sm cursor-pointer shrink-0 border-r border-sol-base03 ${
              filePath === activeFile
                ? "bg-sol-base03 text-sol-base1"
                : "text-sol-base01 hover:text-sol-base1"
            }`}
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
        </div>
      )}
      {/* Content */}
      <div className={`flex-1 min-h-0 bg-sol-base03 ${isTodo ? "overflow-hidden" : "overflow-auto"}`}>
        {isTodo ? (
          <TodoViewer />
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
