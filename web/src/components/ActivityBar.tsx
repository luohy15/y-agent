import { useCallback, type RefCallback } from "react";
import { isPreview } from "../hooks/useAuth";

export type SidebarPanel = "todo" | "chats" | "links" | "notes";

interface ActivityBarProps {
  isLoggedIn: boolean;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  activePanel: SidebarPanel;
  onSelectPanel: (panel: SidebarPanel) => void;
  onOpenFile?: (path: string) => void;
  activeFile?: string | null;
  mobile?: boolean;
  hideGroup1?: boolean;
  chatHide?: boolean;
  onToggleChatHide?: () => void;
  email?: string | null;
  gsiReady?: boolean;
  onLogout?: () => void;
}

const viewerShortcuts = [
  { key: "todo.md", label: "Todo", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </svg>
  )},
  { key: "calendar.md", label: "Calendar", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  )},
  { key: "finance.bean", label: "Finance", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="1" x2="12" y2="23" /><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
    </svg>
  )},
  { key: "emails.md", label: "Email", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" /><polyline points="22,6 12,13 2,6" />
    </svg>
  )},
  { key: "dev.md", label: "Dev", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="6" y1="3" x2="6" y2="15" /><circle cx="18" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M18 9a9 9 0 0 1-9 9" />
    </svg>
  )},
];

export default function ActivityBar({ isLoggedIn, sidebarOpen, onToggleSidebar, activePanel, onSelectPanel, onOpenFile, activeFile, mobile, hideGroup1, chatHide, onToggleChatHide, email, gsiReady, onLogout }: ActivityBarProps) {
  const signinRef: RefCallback<HTMLDivElement> = useCallback((node) => {
    if (!node || isLoggedIn || !gsiReady) return;
    if (!isPreview && (window as any).google?.accounts?.id) {
      (window as any).google.accounts.id.renderButton(node, {
        theme: "filled_black",
        size: "small",
        shape: "pill",
      });
    }
  }, [isLoggedIn, gsiReady]);

  // Show minimal bar with just GitHub + login when not logged in
  if (!isLoggedIn) {
    return (
      <div className={mobile ? "flex shrink-0 bg-sol-base03 flex-col items-start p-3 gap-1 w-full h-full" : "hidden md:flex shrink-0 w-10 bg-sol-base03 border-r border-sol-base02 flex-col items-center pt-2 gap-1"}>
        <div className="mt-auto" />
        <a
          href="https://github.com/luohy15/y-agent"
          target="_blank"
          rel="noopener noreferrer"
          className={mobile
            ? "w-full h-9 flex items-center gap-3 px-3 rounded text-sm text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"
            : "w-8 h-8 flex items-center justify-center rounded text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"
          }
          title="GitHub"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
          {mobile && <span>GitHub</span>}
        </a>
        {mobile ? (
          <div ref={signinRef} className="px-3 py-1" />
        ) : (
          <button
            onClick={() => {
              if (!isPreview && (window as any).google?.accounts?.id) {
                (window as any).google.accounts.id.prompt();
              }
            }}
            className="w-8 h-8 flex items-center justify-center rounded cursor-pointer text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"
            title="Sign in with Google"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" /><polyline points="10 17 15 12 10 7" /><line x1="15" y1="12" x2="3" y2="12" />
            </svg>
          </button>
        )}
      </div>
    );
  }

  const handlePanelClick = (panel: SidebarPanel) => {
    if (mobile) {
      onSelectPanel(panel);
      return;
    }
    if (sidebarOpen && activePanel === panel) {
      onToggleSidebar(); // close sidebar
    } else if (!sidebarOpen) {
      onSelectPanel(panel);
      onToggleSidebar(); // open sidebar
    } else {
      onSelectPanel(panel); // just switch panel
    }
  };

  const btnClass = (active: boolean) => mobile
    ? `w-full h-9 flex items-center gap-3 px-3 rounded cursor-pointer text-sm ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"}`
    : `w-8 h-8 flex items-center justify-center rounded cursor-pointer ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"}`;

  return (
    <div className={mobile ? "flex shrink-0 bg-sol-base03 flex-col items-start p-3 gap-1 w-full h-full" : "hidden md:flex shrink-0 w-10 bg-sol-base03 border-r border-sol-base02 flex-col items-center pt-2 gap-1"}>
      {/* Group 1: Global panels */}
      {!hideGroup1 && (
        <>
          <button
            onClick={() => handlePanelClick("todo")}
            className={btnClass(sidebarOpen && activePanel === "todo")}
            title="Todo"
          >
            <span className="text-base font-bold leading-none">#</span>
            {mobile && <span>Todo</span>}
          </button>
          <button
            onClick={() => handlePanelClick("chats")}
            className={btnClass(sidebarOpen && activePanel === "chats")}
            title="Chats"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 16 16" fill="currentColor">
              <path d="M2 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2.586l1.707 1.707a1 1 0 0 0 1.414 0L9.414 14H14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H2zm2 3h8v1H4V5zm0 3h6v1H4V8z"/>
            </svg>
            {mobile && <span>Chats</span>}
          </button>
          <button
            onClick={() => handlePanelClick("links")}
            className={btnClass(sidebarOpen && activePanel === "links")}
            title="Links"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
            </svg>
            {mobile && <span>Links</span>}
          </button>
          <button
            onClick={() => handlePanelClick("notes")}
            className={btnClass(sidebarOpen && activePanel === "notes")}
            title="Notes"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" />
            </svg>
            {mobile && <span>Notes</span>}
          </button>
          <div className={mobile ? "w-full border-t border-sol-base02 my-1" : "w-6 border-t border-sol-base02 my-1"} />
        </>
      )}
      {/* Group 2: Apps */}
      {viewerShortcuts.map((v) => (
        <button
          key={v.key}
          onClick={() => onOpenFile?.(v.key)}
          className={btnClass(!!chatHide && activeFile === v.key)}
          title={v.label}
        >
          {v.icon}
          {mobile && <span>{v.label}</span>}
        </button>
      ))}
      {/* Bottom: GitHub + Auth */}
      <div className={mobile ? "w-full border-t border-sol-base02 my-1 mt-auto" : "w-6 border-t border-sol-base02 my-1 mt-auto"} />
      <a
        href="https://github.com/luohy15/y-agent"
        target="_blank"
        rel="noopener noreferrer"
        className={mobile
          ? "w-full h-9 flex items-center gap-3 px-3 rounded text-sm text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"
          : "w-8 h-8 flex items-center justify-center rounded text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"
        }
        title="GitHub"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
        {mobile && <span>GitHub</span>}
      </a>
      {isLoggedIn ? (
        <button
          onClick={onLogout}
          className={mobile
            ? "w-full h-9 flex items-center gap-3 px-3 rounded cursor-pointer text-sm text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"
            : "w-8 h-8 flex items-center justify-center rounded cursor-pointer text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"
          }
          title={email ? `${email} — Logout` : "Logout"}
        >
          {email ? (
            <span className={mobile ? "w-5 h-5 rounded-full bg-sol-base02 flex items-center justify-center text-xs font-bold text-sol-base1 shrink-0" : "w-5 h-5 rounded-full bg-sol-base02 flex items-center justify-center text-[10px] font-bold text-sol-base1"}>
              {email[0].toUpperCase()}
            </span>
          ) : (
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
            </svg>
          )}
          {mobile && <span>{email || "Logout"}</span>}
        </button>
      ) : (
        mobile ? (
          <div ref={signinRef} className="px-3 py-1" />
        ) : (
          <button
            onClick={() => {
              if (!isPreview && (window as any).google?.accounts?.id) {
                (window as any).google.accounts.id.prompt();
              }
            }}
            className="w-8 h-8 flex items-center justify-center rounded cursor-pointer text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"
            title="Sign in with Google"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" /><polyline points="10 17 15 12 10 7" /><line x1="15" y1="12" x2="3" y2="12" />
            </svg>
          </button>
        )
      )}
    </div>
  );
}
