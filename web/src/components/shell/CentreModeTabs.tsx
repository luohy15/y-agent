import type { ReactNode } from "react";

export type CentreMode = "files" | "chat";

export interface CentreModeTabsProps {
  mode: CentreMode;
  onModeChange: (mode: CentreMode) => void;
  /** Optional "new chat" / create action after the mode tabs. */
  onNew?: () => void;
  newDisabled?: boolean;
  newTitle?: string;
  /** Extra controls rendered after the built-in buttons (demo chip, etc.). */
  trailing?: ReactNode;
  className?: string;
}

const btnClass = (active: boolean) =>
  `p-1.5 sm:p-1 rounded cursor-pointer ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1"}`;

/**
 * Centre column mode switcher: files | chat | optional new + trailing slot.
 * Presentational only — production and demo both consume this.
 */
export default function CentreModeTabs({
  mode,
  onModeChange,
  onNew,
  newDisabled = false,
  newTitle = "New chat",
  trailing,
  className = "",
}: CentreModeTabsProps) {
  return (
    <div className={`flex items-center gap-1 px-2 py-2 bg-sol-base03 shrink-0 ${className}`.trim()}>
      <button
        onClick={() => onModeChange("files")}
        className={btnClass(mode === "files")}
        title="Notes (Ctrl+`)"
      >
        <svg className="w-4 h-4 sm:w-3.5 sm:h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" />
        </svg>
      </button>
      <button
        onClick={() => onModeChange("chat")}
        className={btnClass(mode === "chat")}
        title="Chat"
      >
        <svg className="w-4 h-4 sm:w-3.5 sm:h-3.5" viewBox="0 0 16 16" fill="currentColor">
          <path d="M2 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2.586l1.707 1.707a1 1 0 0 0 1.414 0L9.414 14H14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H2zm2 3h8v1H4V5zm0 3h6v1H4V8z"/>
        </svg>
      </button>
      {(onNew || trailing) && <div className="w-px h-4 bg-sol-base02 mx-0.5" />}
      {onNew && (
        <button
          onClick={onNew}
          disabled={newDisabled}
          className={`p-1.5 sm:p-1 rounded ${newDisabled ? "text-sol-base01/40 cursor-not-allowed" : "text-sol-base01 hover:text-sol-base1 bg-sol-base02 cursor-pointer"}`}
          title={newTitle}
        >
          <svg className="w-4 h-4 sm:w-3.5 sm:h-3.5" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
            <line x1="7" y1="2" x2="7" y2="12" />
            <line x1="2" y1="7" x2="12" y2="7" />
          </svg>
        </button>
      )}
      {trailing}
    </div>
  );
}
