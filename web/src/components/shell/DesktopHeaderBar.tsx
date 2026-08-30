import type { ReactNode } from "react";

export interface DesktopHeaderBarProps {
  /** Centred meta slot (trace id, VM, bot, work dir, etc.). */
  meta?: ReactNode;
  leftOpen?: boolean;
  bottomOpen?: boolean;
  rightOpen?: boolean;
  maximized?: boolean;
  onToggleLeft?: () => void;
  onToggleBottom?: () => void;
  onToggleRight?: () => void;
  onToggleMaximize?: () => void;
  className?: string;
}

/**
 * Desktop-only header chrome: centred meta slot + layout toggles.
 * Presentational only — production and demo both consume this.
 */
export default function DesktopHeaderBar({
  meta,
  leftOpen = false,
  bottomOpen = false,
  rightOpen = false,
  maximized = false,
  onToggleLeft,
  onToggleBottom,
  onToggleRight,
  onToggleMaximize,
  className = "",
}: DesktopHeaderBarProps) {
  return (
    <div className={`hidden md:flex items-center px-2 py-1 bg-sol-base03 border-b border-sol-base02 shrink-0 ${className}`.trim()}>
      <div className="flex-1 flex justify-center items-center gap-2 text-sol-base01 font-mono text-xs">
        {meta}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {onToggleLeft && (
          <button
            onClick={onToggleLeft}
            className={`p-1 rounded cursor-pointer ${leftOpen ? "text-sol-base1" : "text-sol-base01 hover:text-sol-base1"}`}
            title={leftOpen ? "Hide left sidebar" : "Show left sidebar"}
          >
            <svg className="w-4 h-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1">
              <rect x="1" y="1" width="14" height="14" rx="1" />
              <line x1="5" y1="1" x2="5" y2="15" />
              {leftOpen && <rect x="1" y="1" width="4" height="14" rx="1" fill="currentColor" stroke="none" />}
            </svg>
          </button>
        )}
        {onToggleBottom && (
          <button
            onClick={onToggleBottom}
            className={`p-1 rounded cursor-pointer ${bottomOpen ? "text-sol-base1" : "text-sol-base01 hover:text-sol-base1"}`}
            title={bottomOpen ? "Hide bottom panel" : "Show bottom panel"}
          >
            <svg className="w-4 h-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1">
              <rect x="1" y="1" width="14" height="14" rx="1" />
              <line x1="1" y1="11" x2="15" y2="11" />
              {bottomOpen && <rect x="1" y="11" width="14" height="4" rx="1" fill="currentColor" stroke="none" />}
            </svg>
          </button>
        )}
        {onToggleRight && (
          <button
            onClick={onToggleRight}
            className={`p-1 rounded cursor-pointer ${rightOpen ? "text-sol-base1" : "text-sol-base01 hover:text-sol-base1"}`}
            title={rightOpen ? "Hide right panel" : "Show right panel"}
          >
            <svg className="w-4 h-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1">
              <rect x="1" y="1" width="14" height="14" rx="1" />
              <line x1="11" y1="1" x2="11" y2="15" />
              {rightOpen && <rect x="11" y="1" width="4" height="14" rx="1" fill="currentColor" stroke="none" />}
            </svg>
          </button>
        )}
        {onToggleMaximize && (
          <button
            onClick={onToggleMaximize}
            className={`p-1 rounded cursor-pointer ${maximized ? "text-sol-base1" : "text-sol-base01 hover:text-sol-base1"}`}
            title={maximized ? "Restore panels" : "Maximize center"}
          >
            {maximized ? (
              <svg className="w-4 h-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1">
                <polyline points="14,6 10,6 10,2" />
                <line x1="14" y1="2" x2="10" y2="6" />
                <polyline points="2,10 6,10 6,14" />
                <line x1="2" y1="14" x2="6" y2="10" />
              </svg>
            ) : (
              <svg className="w-4 h-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1">
                <polyline points="10,2 14,2 14,6" />
                <line x1="9" y1="7" x2="14" y2="2" />
                <polyline points="6,14 2,14 2,10" />
                <line x1="7" y1="9" x2="2" y2="14" />
              </svg>
            )}
          </button>
        )}
      </div>
    </div>
  );
}
