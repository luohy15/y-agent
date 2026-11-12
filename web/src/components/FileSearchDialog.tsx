import { Fragment, useState, useEffect, useRef, useCallback } from "react";
import { API, authFetch } from "../api";
import { runHostCommand } from "../host/commands";
import { buildPaletteEntries, type PaletteEntry, type PaletteModule } from "../utils/paletteEntries";

interface FileSearchDialogProps {
  open: boolean;
  onClose: () => void;
  onSelectFile: (path: string) => void;
  vmName?: string | null;
  workDir?: string;
  openFiles?: string[];
  modules?: PaletteModule[];
  onCloseAll?: () => void;
}

export default function FileSearchDialog({ open, onClose, onSelectFile, vmName, workDir, openFiles = [], modules = [], onCloseAll }: FileSearchDialogProps) {
  const vmQuery = (vmName ? `&vm_name=${encodeURIComponent(vmName)}` : "") + (workDir ? `&work_dir=${encodeURIComponent(workDir)}` : "");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<string[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const [searched, setSearched] = useState(false);
  const searchAbortRef = useRef<AbortController | null>(null);

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setQuery("");
      setResults([]);
      setSelectedIndex(0);
      setSearched(false);
      setTimeout(() => inputRef.current?.focus(), 0);
    } else {
      searchAbortRef.current?.abort();
      searchAbortRef.current = null;
    }
  }, [open]);

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    searchAbortRef.current?.abort();
    const ac = new AbortController();
    searchAbortRef.current = ac;
    setLoading(true);
    setSearched(true);
    try {
      const searchPath = workDir || ".";
      // Module-owned search route (todo 3068 cut); host shell owns the dialog (todo 3084 H4).
      const res = await authFetch(`${API}/api/module/file/search?q=${encodeURIComponent(q.trim())}&path=${encodeURIComponent(searchPath)}${vmQuery}`, { signal: ac.signal });
      const data = await res.json();
      if (ac.signal.aborted) return;
      setResults(data.files || []);
      setSelectedIndex(0);
    } catch {
      if (ac.signal.aborted) return;
      setResults([]);
    } finally {
      if (!ac.signal.aborted) setLoading(false);
    }
  }, [vmQuery, workDir]);

  const handleSelect = (entry: PaletteEntry) => {
    if (entry.kind === "module") {
      runHostCommand("module.openView", { slug: entry.slug });
    } else {
      onSelectFile(entry.path);
    }
    onClose();
  };

  const displayList: PaletteEntry[] = searched
    ? results.map((path) => ({ kind: "tab", path, label: path }))
    : buildPaletteEntries(openFiles, modules, query);
  const activeIndex = Math.min(selectedIndex, Math.max(0, displayList.length - 1));

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((activeIndex + 1) % (displayList.length || 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((activeIndex - 1 + (displayList.length || 1)) % (displayList.length || 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (displayList.length > 0) {
        handleSelect(displayList[activeIndex]);
      } else {
        doSearch(query);
      }
    } else if (e.key === "Escape") {
      onClose();
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]" onClick={onClose}>
      <div
        className="w-full max-w-lg bg-sol-base03 border border-sol-base01 rounded shadow-float overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center px-3 py-2 border-b border-sol-base02">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              searchAbortRef.current?.abort();
              setLoading(false);
              setQuery(e.target.value);
              setSelectedIndex(0);
              setSearched(false);
              setResults([]);
            }}
            onKeyDown={handleKeyDown}
            placeholder="Search tabs, modules, or files..."
            className="flex-1 bg-transparent text-sm text-sol-base1 outline-none placeholder:text-sol-base01"
          />
          {loading && <span className="text-sol-base01 text-xs ml-2">...</span>}
          <button
            onClick={() => doSearch(query)}
            className="text-sol-base01 hover:text-sol-base1 cursor-pointer ml-2 shrink-0"
            title="Search"
          >
            <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor">
              <path d="M11.742 10.344a6.5 6.5 0 1 0-1.397 1.398h-.001l3.85 3.85a1 1 0 0 0 1.415-1.414l-3.85-3.85zm-5.242.156a5 5 0 1 1 0-10 5 5 0 0 1 0 10z" />
            </svg>
          </button>
        </div>
        {displayList.length > 0 && (
          <div className="max-h-64 overflow-y-auto py-1">
            {displayList.map((entry, i) => (
              <Fragment key={entry.kind === "tab" ? `tab:${entry.path}` : `module:${entry.slug}`}>
                {!searched && (i === 0 || displayList[i - 1].kind !== entry.kind) && (
                  <div className="flex items-center justify-between px-3 py-1">
                    <span className="text-xs text-sol-base01">{entry.kind === "tab" ? "Open tabs" : "Modules"}</span>
                    {entry.kind === "tab" && onCloseAll && (
                      <button
                        onClick={() => { onCloseAll(); onClose(); }}
                        className="text-xs text-sol-base01 hover:text-sol-base1 cursor-pointer"
                        title="Close all open files"
                      >
                        Close all
                      </button>
                    )}
                  </div>
                )}
                <div
                  onClick={() => handleSelect(entry)}
                  className={`px-3 py-1 text-xs cursor-pointer truncate ${
                    i === activeIndex ? "bg-sol-base02 text-sol-base1" : "text-sol-base0 hover:bg-sol-base02"
                  }`}
                >
                  {entry.label}
                </div>
              </Fragment>
            ))}
          </div>
        )}
        {searched && query && !loading && results.length === 0 && (
          <div className="px-3 py-3 text-xs text-sol-base01 italic">No files found</div>
        )}
      </div>
    </div>
  );
}
