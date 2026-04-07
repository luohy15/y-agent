import { useState, useEffect, useRef } from "react";

export interface CommandAction {
  id: string;
  label: string;
  shortcut?: string;
  execute: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  actions: CommandAction[];
}

export default function CommandPalette({ open, onClose, actions }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const filtered = query.trim()
    ? actions.filter((a) => a.label.toLowerCase().includes(query.trim().toLowerCase()))
    : actions;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => (i + 1) % (filtered.length || 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => (i - 1 + (filtered.length || 1)) % (filtered.length || 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filtered.length > 0) {
        filtered[selectedIndex].execute();
        onClose();
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
            onChange={(e) => { setQuery(e.target.value); setSelectedIndex(0); }}
            onKeyDown={handleKeyDown}
            placeholder="Type a command..."
            className="flex-1 bg-transparent text-sm text-sol-base1 outline-none placeholder:text-sol-base01"
          />
        </div>
        {filtered.length > 0 && (
          <div className="max-h-64 overflow-y-auto py-1">
            {filtered.map((action, i) => (
              <div
                key={action.id}
                onClick={() => { action.execute(); onClose(); }}
                className={`px-3 py-1 text-xs cursor-pointer flex items-center justify-between ${
                  i === selectedIndex ? "bg-sol-base02 text-sol-base1" : "text-sol-base0 hover:bg-sol-base02"
                }`}
              >
                <span>{action.label}</span>
                {action.shortcut && <span className="text-sol-base01 ml-2">{action.shortcut}</span>}
              </div>
            ))}
          </div>
        )}
        {query && filtered.length === 0 && (
          <div className="px-3 py-3 text-xs text-sol-base01 italic">No commands found</div>
        )}
      </div>
    </div>
  );
}
