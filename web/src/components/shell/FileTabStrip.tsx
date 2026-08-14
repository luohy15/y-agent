import { useRef, useState, type ReactNode } from "react";

export interface FileTabItem {
  key: string;
  label: string;
  title?: string;
  dirty?: boolean;
  italic?: boolean;
  /** Defaults to true when onClose is provided. */
  closable?: boolean;
}

export interface FileTabStripProps {
  tabs: FileTabItem[];
  activeKey: string | null;
  onSelect: (key: string) => void;
  onClose?: (key: string) => void;
  onReorder?: (keys: string[]) => void;
  onDoubleClick?: (key: string) => void;
  /** Optional breadcrumb row rendered under the tab strip. */
  breadcrumb?: ReactNode;
  className?: string;
}

export function getBreadcrumbParts(path: string): string[] {
  return path.replace(/^\.\//, "").split("/").filter(Boolean);
}

/** Presentational path breadcrumb used by FileViewer / PublicFileViewer. */
export function FileBreadcrumb({
  path,
  leading,
  trailing,
}: {
  path: string;
  leading?: ReactNode;
  trailing?: ReactNode;
}) {
  const parts = getBreadcrumbParts(path);
  return (
    <div className="flex items-center px-3 py-1 bg-sol-base03 text-xs text-sol-base01 shrink-0 border-b border-sol-base02 overflow-x-auto">
      {leading}
      {parts.map((part, i, arr) => (
        <span key={i} className="flex items-center shrink-0">
          {i > 0 && <span className="mx-1 text-sol-base01">&gt;</span>}
          <span className={i === arr.length - 1 ? "text-sol-base1" : ""}>{part}</span>
        </span>
      ))}
      {trailing}
    </div>
  );
}

/**
 * Shared file tab strip + optional breadcrumb.
 * Used by authenticated FileViewer and public FileViewer.
 */
export default function FileTabStrip({
  tabs,
  activeKey,
  onSelect,
  onClose,
  onReorder,
  onDoubleClick,
  breadcrumb,
  className = "",
}: FileTabStripProps) {
  const dragIdx = useRef<number | null>(null);
  const [dropIdx, setDropIdx] = useState<number | null>(null);
  const keys = tabs.map((t) => t.key);

  return (
    <div className={className}>
      <div className="flex items-center bg-sol-base02 shrink-0 overflow-x-auto">
        {tabs.map((tab, i) => {
          const closable = tab.closable ?? !!onClose;
          return (
            <div
              key={tab.key}
              draggable={!!onReorder}
              onDragStart={(e) => {
                if (!onReorder) return;
                dragIdx.current = i;
                e.dataTransfer.effectAllowed = "move";
              }}
              onDragOver={(e) => {
                if (!onReorder) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
                setDropIdx(i);
              }}
              onDragLeave={() => setDropIdx((cur) => (cur === i ? null : cur))}
              onDrop={(e) => {
                if (!onReorder) return;
                e.preventDefault();
                const from = dragIdx.current;
                if (from !== null && from !== i) {
                  const reordered = [...keys];
                  const [moved] = reordered.splice(from, 1);
                  reordered.splice(i, 0, moved);
                  onReorder(reordered);
                }
                dragIdx.current = null;
                setDropIdx(null);
              }}
              onDragEnd={() => {
                dragIdx.current = null;
                setDropIdx(null);
              }}
              className={`flex items-center gap-1 px-3 py-1.5 text-sm cursor-pointer shrink-0 border-r border-sol-base03 ${
                tab.key === activeKey
                  ? "bg-sol-base03 text-sol-base1"
                  : "text-sol-base01 hover:text-sol-base1"
              } ${dropIdx === i ? "border-l-2 border-l-sol-blue" : ""}`}
              onClick={() => onSelect(tab.key)}
              onDoubleClick={() => onDoubleClick?.(tab.key)}
              title={tab.title ?? tab.label}
            >
              {tab.dirty && <span className="w-2 h-2 rounded-full bg-sol-base0 shrink-0" />}
              <span className={`truncate max-w-[150px] ${tab.italic ? "italic" : ""}`}>{tab.label}</span>
              {closable && onClose && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onClose(tab.key);
                  }}
                  className="text-sol-base01 hover:text-sol-base1 leading-none ml-1 cursor-pointer"
                >
                  &times;
                </button>
              )}
            </div>
          );
        })}
      </div>
      {breadcrumb}
    </div>
  );
}
