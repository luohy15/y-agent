import { useCallback, useMemo, useState, type DragEvent, type ReactNode, type RefCallback } from "react";
import { isPreview } from "../hooks/useAuth";

export type SidebarPanel =
  | "todo"
  | "notes"
  | "chats"
  | "links"
  | "rss"
  | "entity"
  | "files"
  | "reminder"
  | "calendar"
  | "finance"
  | "email"
  | "dev";

interface ActivityBarProps {
  isLoggedIn: boolean;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  activePanel: SidebarPanel;
  onSelectPanel: (panel: SidebarPanel) => void;
  mobile?: boolean;
  email?: string | null;
  gsiReady?: boolean;
  onLogout?: () => void;
}

interface PanelItem {
  key: SidebarPanel;
  label: string;
  icon: ReactNode;
}

const PANEL_ITEMS: PanelItem[] = [
  { key: "todo", label: "Todo", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </svg>
  )},
  { key: "notes", label: "Notes", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" />
    </svg>
  )},
  { key: "chats", label: "Chats", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 16 16" fill="currentColor">
      <path d="M2 2a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2.586l1.707 1.707a1 1 0 0 0 1.414 0L9.414 14H14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H2zm2 3h8v1H4V5zm0 3h6v1H4V8z"/>
    </svg>
  )},
  { key: "links", label: "Links", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
    </svg>
  )},
  { key: "rss", label: "RSS", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 11a9 9 0 0 1 9 9" /><path d="M4 4a16 16 0 0 1 16 16" /><circle cx="5" cy="19" r="1" />
    </svg>
  )},
  { key: "entity", label: "Entities", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 7h-9" /><path d="M14 17H5" /><circle cx="17" cy="17" r="3" /><circle cx="7" cy="7" r="3" />
    </svg>
  )},
  { key: "reminder", label: "Reminders", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  )},
  { key: "files", label: "Files", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
    </svg>
  )},
  { key: "calendar", label: "Calendar", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  )},
  { key: "finance", label: "Finance", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="1" x2="12" y2="23" /><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
    </svg>
  )},
  { key: "email", label: "Email", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" /><polyline points="22,6 12,13 2,6" />
    </svg>
  )},
  { key: "dev", label: "Dev", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="6" y1="3" x2="6" y2="15" /><circle cx="18" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M18 9a9 9 0 0 1-9 9" />
    </svg>
  )},
];

const STORAGE_KEY = "activityBarOrder";
// Legacy keys left behind for migration from earlier app-group layout.
const LEGACY_STORAGE_KEY_PANELS = "activityBarOrderPanels";
const LEGACY_STORAGE_KEY_APPS = "activityBarOrderApps";

// Old app keys → new panel keys.
const APP_TO_PANEL: Record<string, SidebarPanel | null> = {
  "todo.md": null, // folded into existing "todo" panel
  "calendar.md": "calendar",
  "finance.bean": "finance",
  "emails.md": "email",
  "dev.md": "dev",
};

function mergeWithDefaults(parsed: unknown, defaults: SidebarPanel[]): SidebarPanel[] {
  const valid = new Set<SidebarPanel>(defaults);
  const seen = new Set<SidebarPanel>();
  const result: SidebarPanel[] = [];
  if (Array.isArray(parsed)) {
    for (const item of parsed) {
      if (typeof item !== "string") continue;
      const key = item as SidebarPanel;
      if (!valid.has(key) || seen.has(key)) continue;
      result.push(key);
      seen.add(key);
    }
  }
  for (const d of defaults) {
    if (!seen.has(d)) {
      result.push(d);
      seen.add(d);
    }
  }
  return result;
}

function migrateUnifiedV1(raw: string, defaults: SidebarPanel[]): SidebarPanel[] | null {
  // Old unified shape: [{ group: 'panel' | 'app', key: string }]
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    const migrated: SidebarPanel[] = [];
    let sawOld = false;
    for (const item of parsed) {
      if (!item || typeof item !== "object") continue;
      const group = (item as { group?: unknown }).group;
      const key = (item as { key?: unknown }).key;
      if (typeof key !== "string") continue;
      if (group === "panel") {
        migrated.push(key as SidebarPanel);
        sawOld = true;
      } else if (group === "app") {
        const mapped = APP_TO_PANEL[key];
        if (mapped) migrated.push(mapped);
        sawOld = true;
      }
    }
    if (!sawOld) return null;
    return mergeWithDefaults(migrated, defaults);
  } catch {
    return null;
  }
}

function migrateLegacySplit(defaults: SidebarPanel[]): SidebarPanel[] | null {
  if (typeof window === "undefined") return null;
  const legacyPanels = window.localStorage.getItem(LEGACY_STORAGE_KEY_PANELS);
  const legacyApps = window.localStorage.getItem(LEGACY_STORAGE_KEY_APPS);
  if (!legacyPanels && !legacyApps) return null;
  const migrated: SidebarPanel[] = [];
  const pushPanelKeys = (raw: string | null) => {
    if (!raw) return;
    try {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr)) {
        for (const k of arr) if (typeof k === "string") migrated.push(k as SidebarPanel);
      }
    } catch { /* ignore */ }
  };
  const pushAppKeys = (raw: string | null) => {
    if (!raw) return;
    try {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr)) {
        for (const k of arr) {
          if (typeof k !== "string") continue;
          const mapped = APP_TO_PANEL[k];
          if (mapped) migrated.push(mapped);
        }
      }
    } catch { /* ignore */ }
  };
  pushPanelKeys(legacyPanels);
  pushAppKeys(legacyApps);
  return mergeWithDefaults(migrated, defaults);
}

function loadOrder(defaults: SidebarPanel[]): SidebarPanel[] {
  try {
    if (typeof window === "undefined") return defaults.slice();
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      // Try new shape first (string[]); fall through to legacy migration if needed.
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.every(x => typeof x === "string")) {
          return mergeWithDefaults(parsed, defaults);
        }
      } catch { /* ignore */ }
      const migrated = migrateUnifiedV1(raw, defaults);
      if (migrated) {
        saveOrder(migrated);
        return migrated;
      }
    }
    const legacyMigrated = migrateLegacySplit(defaults);
    if (legacyMigrated) {
      saveOrder(legacyMigrated);
      try {
        window.localStorage.removeItem(LEGACY_STORAGE_KEY_PANELS);
        window.localStorage.removeItem(LEGACY_STORAGE_KEY_APPS);
      } catch { /* ignore */ }
      return legacyMigrated;
    }
    return defaults.slice();
  } catch {
    return defaults.slice();
  }
}

function saveOrder(order: SidebarPanel[]) {
  try {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(order));
    }
  } catch {
    // ignore
  }
}

interface DragState { key: SidebarPanel }
interface DropTargetState { key: SidebarPanel; pos: "before" | "after" }

export default function ActivityBar({ isLoggedIn, sidebarOpen, onToggleSidebar, activePanel, onSelectPanel, mobile, email, gsiReady, onLogout }: ActivityBarProps) {
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

  const defaultOrder = useMemo<SidebarPanel[]>(() => PANEL_ITEMS.map(p => p.key), []);

  const [order, setOrder] = useState<SidebarPanel[]>(() => loadOrder(defaultOrder));

  const panelByKey = useMemo(() => {
    const m = new Map<SidebarPanel, PanelItem>();
    PANEL_ITEMS.forEach(p => m.set(p.key, p));
    return m;
  }, []);

  const [drag, setDrag] = useState<DragState | null>(null);
  const [dropTarget, setDropTarget] = useState<DropTargetState | null>(null);

  const dragEnabled = !mobile;

  const onItemDragStart = (key: SidebarPanel) => (e: DragEvent<HTMLDivElement>) => {
    if (!dragEnabled) return;
    setDrag({ key });
    try {
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", key);
    } catch {
      // ignore
    }
  };

  const onItemDragOver = (key: SidebarPanel) => (e: DragEvent<HTMLDivElement>) => {
    if (!dragEnabled || !drag) return;
    e.preventDefault();
    try { e.dataTransfer.dropEffect = "move"; } catch { /* ignore */ }
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const midY = rect.top + rect.height / 2;
    const pos: "before" | "after" = e.clientY < midY ? "before" : "after";
    if (!dropTarget || dropTarget.key !== key || dropTarget.pos !== pos) {
      setDropTarget({ key, pos });
    }
  };

  const onItemDrop = (key: SidebarPanel) => (e: DragEvent<HTMLDivElement>) => {
    if (!dragEnabled || !drag) {
      setDrag(null);
      setDropTarget(null);
      return;
    }
    e.preventDefault();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const midY = rect.top + rect.height / 2;
    const pos: "before" | "after" = e.clientY < midY ? "before" : "after";
    applyReorder(drag.key, key, pos);
    setDrag(null);
    setDropTarget(null);
  };

  const onItemDragEnd = () => {
    setDrag(null);
    setDropTarget(null);
  };

  function applyReorder(fromKey: SidebarPanel, toKey: SidebarPanel, pos: "before" | "after") {
    if (fromKey === toKey) return;
    const current = order.slice();
    const fromIdx = current.indexOf(fromKey);
    const toIdx = current.indexOf(toKey);
    if (fromIdx === -1 || toIdx === -1) return;
    const moving = current[fromIdx];
    let insertAt = pos === "after" ? toIdx + 1 : toIdx;
    current.splice(fromIdx, 1);
    if (fromIdx < insertAt) insertAt -= 1;
    if (insertAt === fromIdx) return;
    current.splice(insertAt, 0, moving);
    setOrder(current);
    saveOrder(current);
  }

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

  const btnClass = (active: boolean, dragged: boolean) => {
    const base = mobile
      ? `w-full h-9 flex items-center gap-3 px-3 rounded cursor-pointer text-sm ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"}`
      : `w-8 h-8 flex items-center justify-center rounded cursor-pointer ${active ? "text-sol-base1 bg-sol-base02" : "text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"}`;
    return dragged ? `${base} opacity-50` : base;
  };

  const wrapperClass = () => (mobile ? "relative w-full" : "relative");

  const isDifferentFromDrag = (key: SidebarPanel) => !!drag && drag.key !== key;

  const indicator = (key: SidebarPanel, side: "before" | "after") => {
    const show = !!(dropTarget && dropTarget.key === key && dropTarget.pos === side && isDifferentFromDrag(key));
    if (!show) return null;
    const sideCls = side === "before" ? "-top-0.5" : "-bottom-0.5";
    return (
      <div className={`pointer-events-none absolute left-0 right-0 ${sideCls} h-0.5 rounded-full bg-sol-blue`} />
    );
  };

  return (
    <div className={mobile ? "flex shrink-0 bg-sol-base03 flex-col items-start p-3 gap-1 w-full h-full" : "hidden md:flex shrink-0 w-10 bg-sol-base03 border-r border-sol-base02 flex-col items-center pt-2 gap-1"}>
      {order.map((key) => {
        const p = panelByKey.get(key);
        if (!p) return null;
        const isDragged = !!(drag && drag.key === p.key);
        const active = sidebarOpen && activePanel === p.key;
        return (
          <div
            key={`panel:${p.key}`}
            className={wrapperClass()}
            draggable={dragEnabled}
            onDragStart={onItemDragStart(p.key)}
            onDragOver={onItemDragOver(p.key)}
            onDrop={onItemDrop(p.key)}
            onDragEnd={onItemDragEnd}
          >
            {indicator(p.key, "before")}
            <button
              onClick={() => handlePanelClick(p.key)}
              className={btnClass(active, isDragged)}
              title={p.label}
            >
              {p.icon}
              {mobile && <span>{p.label}</span>}
            </button>
            {indicator(p.key, "after")}
          </div>
        );
      })}
      {/* Bottom: GitHub + Auth */}
      <a
        href="https://github.com/luohy15/y-agent"
        target="_blank"
        rel="noopener noreferrer"
        className={mobile
          ? "mt-auto w-full h-9 flex items-center gap-3 px-3 rounded text-sm text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"
          : "mt-auto w-8 h-8 flex items-center justify-center rounded text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"
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
