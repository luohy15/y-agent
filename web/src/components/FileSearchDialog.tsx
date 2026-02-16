import { useState, useEffect, useRef, useCallback } from "react";
import { API, authFetch } from "../api";

interface FileSearchDialogProps {
  open: boolean;
  onClose: () => void;
  onSelectFile: (path: string) => void;
}

export default function FileSearchDialog({ open, onClose, onSelectFile }: FileSearchDialogProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<string[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<number | null>(null);

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setQuery("");
      setResults([]);
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  // Debounced search
  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setLoading(true);
    try {
      const res = await authFetch(`${API}/api/file/search?q=${encodeURIComponent(q.trim())}`);
      const data = await res.json();
      setResults(data.files || []);
      setSelectedIndex(0);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleInputChange = (value: string) => {
    setQuery(value);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => doSearch(value), 200);
  };

  const handleSelect = (path: string) => {
    onSelectFile(path);
    onClose();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && results.length > 0) {
      e.preventDefault();
      handleSelect(results[selectedIndex]);
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
            onChange={(e) => handleInputChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search files by name..."
            className="flex-1 bg-transparent text-sm text-sol-base1 outline-none placeholder:text-sol-base01"
          />
          {loading && <span className="text-sol-base01 text-xs ml-2">...</span>}
        </div>
        {results.length > 0 && (
          <div className="max-h-64 overflow-y-auto py-1">
            {results.map((file, i) => (
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
        {query && !loading && results.length === 0 && (
          <div className="px-3 py-3 text-xs text-sol-base01 italic">No files found</div>
        )}
      </div>
    </div>
  );
}
