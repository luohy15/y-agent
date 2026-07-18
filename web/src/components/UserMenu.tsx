import { useEffect, useRef, useState } from "react";
import { useTheme } from "../hooks/useTheme";
import SettingsModal from "./SettingsModal";
import UserInfoModal from "./UserInfoModal";

interface UserMenuProps {
  email: string | null;
  isLoggedIn: boolean;
  mobile: boolean;
  onLogout: () => void;
}

export default function UserMenu({ email, isLoggedIn, mobile, onLogout }: UserMenuProps) {
  const [open, setOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const { theme, setTheme } = useTheme(isLoggedIn);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const keyHandler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    document.addEventListener("keydown", keyHandler);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("keydown", keyHandler);
    };
  }, [open]);

  const initial = email ? email[0].toUpperCase() : null;

  const triggerClass = mobile
    ? "w-full h-9 flex items-center gap-3 px-3 rounded cursor-pointer text-sm text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"
    : "w-8 h-8 flex items-center justify-center rounded cursor-pointer text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02";

  const avatarBadge = initial ? (
    <span
      className={
        mobile
          ? "w-5 h-5 rounded-full bg-sol-base02 flex items-center justify-center text-xs font-bold text-sol-base1 shrink-0"
          : "w-5 h-5 rounded-full bg-sol-base02 flex items-center justify-center text-[10px] font-bold text-sol-base1"
      }
    >
      {initial}
    </span>
  ) : (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
    </svg>
  );

  return (
    <>
      <div ref={wrapperRef} className={mobile ? "relative w-full" : "relative"}>
        <button
          onClick={() => setOpen((v) => !v)}
          className={triggerClass}
          title={email || "Account"}
          aria-haspopup="menu"
          aria-expanded={open}
        >
          {avatarBadge}
          {mobile && <span className="truncate">{email || "Account"}</span>}
        </button>
        {open && (
          <div
            role="menu"
            className={
              mobile
                ? "absolute bottom-full left-0 right-0 mb-1 z-50 bg-sol-base02 border border-sol-base01 rounded shadow-lg py-1"
                : "absolute bottom-0 left-full ml-2 z-50 bg-sol-base02 border border-sol-base01 rounded shadow-lg py-1 min-w-[180px]"
            }
          >
            {email && (
              <div className="px-3 py-1.5 text-[11px] text-sol-base01 truncate border-b border-sol-base03 mb-1">
                {email}
              </div>
            )}
            <button
              role="menuitem"
              onClick={() => { setOpen(false); setInfoOpen(true); }}
              className="w-full text-left px-3 py-1.5 text-sm cursor-pointer hover:bg-sol-base03 text-sol-base1 flex items-center gap-2"
            >
              <svg className="w-3.5 h-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
              </svg>
              <span>User info</span>
            </button>
            <button
              role="menuitem"
              onClick={() => { setOpen(false); setSettingsOpen(true); }}
              className="w-full text-left px-3 py-1.5 text-sm cursor-pointer hover:bg-sol-base03 text-sol-base1 flex items-center gap-2"
            >
              <svg className="w-3.5 h-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.12 2.12-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.55V20h-3v-.09a1.7 1.7 0 0 0-1.03-1.55 1.7 1.7 0 0 0-1.88.34l-.06.06-2.12-2.12.06-.06A1.7 1.7 0 0 0 7 14.7a1.7 1.7 0 0 0-1.55-1.03H5v-3h.09A1.7 1.7 0 0 0 6.64 9.64a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.12-2.12.06.06A1.7 1.7 0 0 0 10.3 6a1.7 1.7 0 0 0 1.03-1.55V4.4h3v.09A1.7 1.7 0 0 0 15.36 6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.12 2.12-.06.06A1.7 1.7 0 0 0 19 9.64a1.7 1.7 0 0 0 1.55 1.03h.12v3h-.09A1.7 1.7 0 0 0 19.4 15Z" />
              </svg>
              <span>Settings</span>
            </button>
            <button
              role="menuitem"
              onClick={() => { setOpen(false); onLogout(); }}
              className="w-full text-left px-3 py-1.5 text-sm cursor-pointer hover:bg-sol-base03 text-sol-base1 flex items-center gap-2"
            >
              <svg className="w-3.5 h-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
              </svg>
              <span>Sign out</span>
            </button>
          </div>
        )}
      </div>
      <UserInfoModal open={infoOpen} email={email} onClose={() => setInfoOpen(false)} />
      <SettingsModal
        open={settingsOpen}
        theme={theme}
        onThemeChange={setTheme}
        onClose={() => setSettingsOpen(false)}
      />
    </>
  );
}
