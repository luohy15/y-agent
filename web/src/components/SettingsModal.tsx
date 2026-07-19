import { useEffect, useRef, useState } from "react";
import {
  DARK_VARIANTS,
  LIGHT_VARIANTS,
  MODES,
  type DarkVariant,
  type LightVariant,
  type Mode,
  type Theme,
  type ThemePrefs,
} from "../utils/theme";

interface SettingsModalProps {
  open: boolean;
  prefs: ThemePrefs;
  onModeChange: (mode: Mode) => void;
  onLightVariantChange: (variant: LightVariant) => void;
  onDarkVariantChange: (variant: DarkVariant) => void;
  onClose: () => void;
}

function AaSwatch({ variant }: { variant: Theme }) {
  return (
    <span
      data-theme={variant}
      className="flex h-5 w-5 shrink-0 items-center justify-center rounded border border-sol-base01 bg-sol-base03 text-[10px] font-semibold"
    >
      <span className="text-sol-base1">Aa</span>
    </span>
  );
}

interface VariantDropdownProps<V extends string> {
  label: string;
  options: { value: V; label: string }[];
  value: V;
  onChange: (value: V) => void;
  open: boolean;
  onToggle: () => void;
  onCloseOnly: () => void;
}

function VariantDropdown<V extends string>({
  label,
  options,
  value,
  onChange,
  open,
  onToggle,
  onCloseOnly,
}: VariantDropdownProps<V>) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const active = options.find((option) => option.value === value) ?? options[0];

  useEffect(() => {
    if (!open) return;
    const handler = (event: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        onCloseOnly();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open, onCloseOnly]);

  return (
    <div ref={wrapperRef} className="relative">
      <div className="text-xs font-medium text-sol-base1">{label}</div>
      <button
        type="button"
        onClick={onToggle}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="mt-2 flex w-full items-center gap-2 rounded border border-sol-base02 px-3 py-2 text-left text-sm text-sol-base0 hover:border-sol-base01 cursor-pointer"
      >
        <AaSwatch variant={active.value as Theme} />
        <span className="flex-1">{active.label}</span>
        <svg className="h-3.5 w-3.5 shrink-0 text-sol-base01" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {open && (
        <div
          role="listbox"
          aria-label={label}
          className="absolute left-0 right-0 top-full z-10 mt-1 overflow-hidden rounded border border-sol-base01 bg-sol-base03 shadow-lg"
        >
          {options.map((option) => {
            const isActive = option.value === value;
            return (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={isActive}
                onClick={() => {
                  onChange(option.value);
                  onCloseOnly();
                }}
                className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm cursor-pointer ${
                  isActive ? "bg-sol-base02 text-sol-base1" : "text-sol-base0 hover:bg-sol-base02"
                }`}
              >
                <AaSwatch variant={option.value as Theme} />
                <span className="flex-1">{option.label}</span>
                {isActive && (
                  <svg className="h-3.5 w-3.5 shrink-0 text-sol-blue" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function SettingsModal({
  open,
  prefs,
  onModeChange,
  onLightVariantChange,
  onDarkVariantChange,
  onClose,
}: SettingsModalProps) {
  const [openDropdown, setOpenDropdown] = useState<"light" | "dark" | null>(null);
  const openDropdownRef = useRef(openDropdown);
  openDropdownRef.current = openDropdown;

  useEffect(() => {
    if (!open) return;
    setOpenDropdown(null);
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (openDropdownRef.current) {
        setOpenDropdown(null);
      } else {
        onClose();
      }
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

          <VariantDropdown
            label="Light appearance"
            options={LIGHT_VARIANTS}
            value={prefs.lightVariant}
            onChange={onLightVariantChange}
            open={openDropdown === "light"}
            onToggle={() => setOpenDropdown((current) => (current === "light" ? null : "light"))}
            onCloseOnly={() => setOpenDropdown(null)}
          />

          <VariantDropdown
            label="Dark appearance"
            options={DARK_VARIANTS}
            value={prefs.darkVariant}
            onChange={onDarkVariantChange}
            open={openDropdown === "dark"}
            onToggle={() => setOpenDropdown((current) => (current === "dark" ? null : "dark"))}
            onCloseOnly={() => setOpenDropdown(null)}
          />
        </div>
      </div>
    </div>
  );
}
