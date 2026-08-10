import { useEffect } from "react";
import { MODES, type Mode, type ThemePrefs } from "../utils/theme";

interface SettingsModalProps {
  open: boolean;
  prefs: ThemePrefs;
  onModeChange: (mode: Mode) => void;
  onClose: () => void;
}

export default function SettingsModal({ open, prefs, onModeChange, onClose }: SettingsModalProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        className="w-full max-w-md bg-sol-base03 border border-sol-base01 rounded-lg shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-sol-base02">
          <div>
            <h2 id="settings-title" className="text-sol-base1 text-sm font-semibold">Settings</h2>
            <p className="mt-0.5 text-sol-base01 text-xs">Appearance is saved to your account.</p>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 p-1 text-sol-base01 hover:text-sol-base1 rounded cursor-pointer"
            title="Close"
            aria-label="Close settings"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div className="px-4 py-4 space-y-4">
          <div>
            <div className="text-xs font-medium text-sol-base1">Mode</div>
            <div role="radiogroup" aria-label="Mode" className="grid grid-cols-3 gap-1 mt-2 rounded border border-sol-base02 p-1">
              {MODES.map((option) => {
                const active = option.value === prefs.mode;
                return (
                  <button
                    key={option.value}
                    role="radio"
                    aria-checked={active}
                    onClick={() => onModeChange(option.value)}
                    className={`rounded px-2 py-1.5 text-center text-sm cursor-pointer transition-colors ${
                      active
                        ? "bg-sol-base02 text-sol-base1"
                        : "text-sol-base00 hover:bg-sol-base02 hover:text-sol-base1"
                    }`}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
