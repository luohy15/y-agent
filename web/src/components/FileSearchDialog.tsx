import { useState, useEffect, useRef, useCallback } from "react";
import { API, authFetch } from "../api";

interface FileSearchDialogProps {
  open: boolean;
  onClose: () => void;
  onSelectFile: (path: string) => void;
  vmName?: string | null;
  workDir?: string;
  openFiles?: string[];
}

export default function FileSearchDialog({ open, onClose, onSelectFile, vmName, workDir, openFiles = [] }: FileSearchDialogProps) {
  const vmQuery = (vmName ? `&vm_name=${encodeURIComponent(vmName)}` : "") + (workDir ? `&work_dir=${encodeURIComponent(workDir)}` : "");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<string[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const [searched, setSearched] = useState(false);

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setQuery("");
      setResults([]);
      setSelectedIndex(0);
      setSearched(false);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setLoading(true);
    setSearched(true);
    try {
      const searchPath = workDir || ".";
      const res = await authFetch(`${API}/api/file/search?q=${encodeURIComponent(q.trim())}&path=${encodeURIComponent(searchPath)}${vmQuery}`);
      const data = await res.json();
      setResults(data.files || []);
      setSelectedIndex(0);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [vmQuery]);

  const handleSelect = (path: string) => {
    onSelectFile(path);
    onClose();
  };

  // Filter open files by query (before submit)
  const filteredOpenFiles = query.trim()
    ? openFiles.filter((f) => f.toLowerCase().includes(query.trim().toLowerCase()))
    : openFiles;
  const showOpenFiles = !searched && filteredOpenFiles.length > 0;
  const displayList = showOpenFiles ? filteredOpenFiles : results;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => (i + 1) % (displayList.length || 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => (i - 1 + (displayList.length || 1)) % (displayList.length || 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (displayList.length > 0) {
        handleSelect(displayList[selectedIndex]);
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
        className="w-full max-w-lg bg-sol-base03 border border-sol-base01 rounded-lg shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center px-3 py-2 border-b border-sol-base02">
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search files by name..."
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
            {showOpenFiles && <div className="px-3 py-1 text-xs text-sol-base01">Open files</div>}
            {displayList.map((file, i) => (
              <div
                key={file}
                onClick={() => handleSelect(file)}
                className={`px-3 py-1 text-xs cursor-pointer truncate ${
                  i === selectedIndex ? "bg-sol-base02 text-sol-base1" : "text-sol-base0 hover:bg-sol-base02"
                }`}
              >
                {file}
              </div>
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
