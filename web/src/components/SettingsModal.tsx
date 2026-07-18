import { useEffect } from "react";
import { THEMES, type Theme } from "../utils/theme";

interface SettingsModalProps {
  open: boolean;
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
  onClose: () => void;
}

export default function SettingsModal({ open, theme, onThemeChange, onClose }: SettingsModalProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
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
        className="w-full max-w-md bg-sol-base03 border border-sol-base01 rounded-lg shadow-2xl overflow-hidden"
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
        <div className="px-4 py-4">
          <div className="text-xs font-medium text-sol-base1">Theme</div>
          <div role="radiogroup" aria-label="Theme" className="grid grid-cols-2 gap-2 mt-2">
            {THEMES.map((option) => {
              const active = option.value === theme;
              return (
                <button
                  key={option.value}
                  role="radio"
                  aria-checked={active}
                  onClick={() => onThemeChange(option.value)}
                  className={`flex items-center gap-2 rounded border px-3 py-2 text-left text-sm cursor-pointer transition-colors ${
                    active
                      ? "border-sol-blue bg-sol-base02 text-sol-base1"
                      : "border-sol-base02 text-sol-base00 hover:border-sol-base01 hover:bg-sol-base02"
                  }`}
                >
                  <span className={`flex h-4 w-4 items-center justify-center rounded-full border ${active ? "border-sol-blue text-sol-blue" : "border-sol-base01"}`}>
                    {active && <span className="h-2 w-2 rounded-full bg-current" />}
                  </span>
                  <span>{option.label}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
