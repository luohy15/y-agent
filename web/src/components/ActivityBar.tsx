import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type RefCallback } from "react";
import { isPreview } from "../hooks/useAuth";
import { useUserPreference, type SyncStatus } from "../hooks/useUserPreference";
import type { Module } from "../host/artifacts";
import { buildModulePanelItems, type PanelItem } from "./panelCatalog";
import UserMenu from "./UserMenu";

export type BuiltInSidebarPanel =
  | "links"
  | "rss"
  | "entity"
  | "reminder"
  | "routine"
  | "english"
  | "email"
  | "dev";

export type SidebarPanel = BuiltInSidebarPanel | `artifact:${string}`;

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
  artifacts?: Module[];
  artifactsLoaded?: boolean;
  /**
   * Keys rendered dimmed, inert, and grouped after a divider (design-3158).
   * Default empty: authenticated app keeps its existing ordering/selection.
   * When set, these keys are excluded from the live reorderable group and
   * rendered after a divider with `data-unavailable`.
   */
  unavailableKeys?: readonly string[];
  /** Optional title override for an unavailable key (defaults to label + " — not part of the demo"). */
  unavailableTitles?: Partial<Record<string, string>>;
  /** Optional click handler for unavailable items (e.g. demo toast). Default: no-op. */
  onUnavailableSelect?: (key: string) => void;
  /**
   * Optional explicit ordering for the live (available) group. When omitted,
   * the authenticated reorderable order is used. Demo passes a fixed order.
   */
  availableOrder?: readonly string[];
  /**
   * When true, render the GitHub + sign-in footer even if `isLoggedIn` is true
   * (public demo shell: design-3158 shows sign-in, not a user menu). Default
   * false preserves authenticated behavior.
   */
  forceSignInFooter?: boolean;
  /**
   * Presentation-only rail (public demo, todo 3158 H6 round 1). Keeps the
   * signed-in rail shape (`isLoggedIn` icons/groups) while disabling every
   * durable path: no `/api/user-preference`, no localStorage read/migrate/write,
   * no drag-reorder persistence. Default false preserves authenticated behavior.
   */
  presentationOnly?: boolean;
}

export const BUILT_IN_PANEL_ITEMS: PanelItem<SidebarPanel>[] = [
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
  { key: "routine", label: "Routines", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" /><polyline points="12 7 12 12 15 14" />
    </svg>
  )},
  { key: "english", label: "English", icon: (
    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
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

export function buildActivityPanelItems(artifacts: Module[]): PanelItem<SidebarPanel>[] {
  return [...BUILT_IN_PANEL_ITEMS, ...buildModulePanelItems(artifacts)];
}

const STORAGE_KEY = "activityBarOrder";
// Legacy keys left behind for migration from earlier app-group layout.
const LEGACY_STORAGE_KEY_PANELS = "activityBarOrderPanels";
const LEGACY_STORAGE_KEY_APPS = "activityBarOrderApps";

// Old app keys → new panel keys.
const APP_TO_PANEL: Record<string, SidebarPanel | null> = {
  "todo.md": "artifact:todo",
  "calendar.md": "artifact:calendar",
  "finance.bean": "artifact:finance",
  "emails.md": "email",
  "dev.md": "dev",
  chats: "artifact:chat",
  // C1: fixed left module-backed entries become artifact panel keys.
  notes: "artifact:note",
  files: "artifact:file",
  // Todo 3164: built-in Tags panel identity becomes the tag module panel key.
  tags: "artifact:tag",
};

/** Map a persisted activity-bar key through the one-shot APP_TO_PANEL renames. */
export function migrateActivityPanelKey(key: string): SidebarPanel {
  return (APP_TO_PANEL[key] ?? key) as SidebarPanel;
}

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

  const insertMissingByDefaultPosition = (key: SidebarPanel) => {
    const defaultIdx = defaults.indexOf(key);
    let insertAt = result.length;
    for (let i = defaultIdx + 1; i < defaults.length; i += 1) {
      const nextIdx = result.indexOf(defaults[i]);
      if (nextIdx !== -1) {
        insertAt = nextIdx;
        break;
      }
    }
    result.splice(insertAt, 0, key);
    seen.add(key);
  };

  for (const d of defaults) {
    if (!seen.has(d)) {
      insertMissingByDefaultPosition(d);
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
          const migrated = parsed.map((key) => migrateActivityPanelKey(key));
          const merged = mergeWithDefaults(migrated, defaults);
          if (migrated.some((key, index) => key !== parsed[index])) saveOrder(merged);
          return merged;
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

export default function ActivityBar({ isLoggedIn, sidebarOpen, onToggleSidebar, activePanel, onSelectPanel, mobile, email, gsiReady, onLogout, artifacts = [], artifactsLoaded = true, unavailableKeys = [], unavailableTitles, onUnavailableSelect, availableOrder, forceSignInFooter = false, presentationOnly = false }: ActivityBarProps) {
  const signinRef: RefCallback<HTMLDivElement> = useCallback((node) => {
    if (!node || isLoggedIn || !gsiReady || presentationOnly) return;
    if (!isPreview && (window as any).google?.accounts?.id) {
      (window as any).google.accounts.id.renderButton(node, {
        theme: "filled_black",
        size: "small",
        shape: "pill",
      });
    }
  }, [isLoggedIn, gsiReady, presentationOnly]);

  const panelItems = useMemo(() => buildActivityPanelItems(artifacts), [artifacts]);
  const defaultOrder = useMemo<SidebarPanel[]>(() => panelItems.map(p => p.key), [panelItems]);

  // Presentation-only: never touch localStorage (no load/migrate/write). Memory
  // order is just the catalog defaults so availableOrder can filter over it.
  const [order, setOrder] = useState<SidebarPanel[]>(() =>
    presentationOnly
      ? BUILT_IN_PANEL_ITEMS.map((panel) => panel.key)
      : loadOrder(BUILT_IN_PANEL_ITEMS.map((panel) => panel.key)),
  );

  const pref = useUserPreference<SidebarPanel[]>("activityBarOrder", {
    enabled: isLoggedIn && !presentationOnly,
  });
  useEffect(() => {
    if (presentationOnly) {
      // Stay in memory only: adopt catalog defaults when artifacts load, never
      // read or migrate a visitor's production rail order.
      if (!artifactsLoaded) return;
      setOrder(defaultOrder);
      return;
    }
    if (!artifactsLoaded) return;
    setOrder(loadOrder(defaultOrder));
  }, [artifactsLoaded, defaultOrder, presentationOnly]);

  // True after the user has reordered locally; suppresses one-shot server overwrite
  // so a slow GET doesn't snap their fresh change back to an older value.
  const userTouchedRef = useRef(false);
  // Per-login bootstrap guard: once we've reconciled the initial server value
  // (or pushed local→server when server is empty), don't run that branch again.
  const reconciledRef = useRef(false);

  useEffect(() => {
    if (!isLoggedIn || presentationOnly) {
      userTouchedRef.current = false;
      reconciledRef.current = false;
    }
  }, [isLoggedIn, presentationOnly]);

  useEffect(() => {
    if (presentationOnly) return;
    if (!isLoggedIn || !artifactsLoaded || !pref.loaded || reconciledRef.current) return;
    reconciledRef.current = true;
    if (pref.serverValue && Array.isArray(pref.serverValue)) {
      if (userTouchedRef.current) return;
      const migrated = pref.serverValue.map((key) => migrateActivityPanelKey(key));
      const merged = mergeWithDefaults(migrated, defaultOrder);
      setOrder(merged);
      saveOrder(merged);
      if (migrated.some((key, index) => key !== pref.serverValue?.[index])) pref.setValue(merged);
    } else {
      // Server has no value — bootstrap with local order if it differs from default
      const isDefault =
        order.length === defaultOrder.length &&
        order.every((k, i) => k === defaultOrder[i]);
      if (!isDefault) {
        pref.setValue(order);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoggedIn, artifactsLoaded, pref.loaded, pref.serverValue, defaultOrder]);

  // Sync status pill: show on error/offline, briefly flash "Synced" after recovery.
  type PillVariant = "error" | "offline" | "success";
  const [pill, setPill] = useState<PillVariant | null>(null);
  const prevPillRef = useRef<PillVariant | null>(null);
  useEffect(() => {
    if (pref.status === "error") {
      setPill("error");
      prevPillRef.current = "error";
      return;
    }
    if (pref.status === "offline") {
      setPill("offline");
      prevPillRef.current = "offline";
      return;
    }
    if (pref.status === "synced" && (prevPillRef.current === "error" || prevPillRef.current === "offline")) {
      setPill("success");
      prevPillRef.current = "success";
      const t = window.setTimeout(() => setPill(null), 1500);
      return () => window.clearTimeout(t);
    }
    if (pref.status === "synced" || pref.status === "idle") {
      // Clear any lingering success pill on subsequent successful syncs.
      if (prevPillRef.current === "success") {
        setPill(null);
        prevPillRef.current = null;
      }
    }
  }, [pref.status]);

  const panelByKey = useMemo(() => {
    const m = new Map<SidebarPanel, PanelItem<SidebarPanel>>();
    panelItems.forEach(p => m.set(p.key, p));
    return m;
  }, [panelItems]);

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
    if (presentationOnly) return;
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
    if (isLoggedIn) {
      userTouchedRef.current = true;
      pref.setValue(current);
    }
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

  const unavailableSet = useMemo(() => new Set(unavailableKeys), [unavailableKeys]);
  const liveOrder = useMemo(() => {
    if (availableOrder && availableOrder.length > 0) {
      return availableOrder.filter((key) => panelByKey.has(key as SidebarPanel) && !unavailableSet.has(key)) as SidebarPanel[];
    }
    return order.filter((key) => !unavailableSet.has(key));
  }, [availableOrder, order, panelByKey, unavailableSet]);
  const unavailableOrdered = useMemo(() => {
    if (unavailableKeys.length === 0) return [] as SidebarPanel[];
    // Preserve caller order; fall back to any remaining unavailable keys present in the catalog.
    const seen = new Set<string>();
    const result: SidebarPanel[] = [];
    for (const key of unavailableKeys) {
      if (seen.has(key)) continue;
      if (!panelByKey.has(key as SidebarPanel)) continue;
      seen.add(key);
      result.push(key as SidebarPanel);
    }
    return result;
  }, [unavailableKeys, panelByKey]);

  const panelButtons = liveOrder.map((key) => {
    const p = panelByKey.get(key);
    if (!p) return null;
    const isDragged = !!(drag && drag.key === p.key);
    const active = sidebarOpen && activePanel === p.key;
    // Drag reorder stays signed-in-only; presentationOnly / fixed availableOrder
    // disable drag so demo never rewrites rail order.
    const canDrag = dragEnabled && !availableOrder && !presentationOnly;
    return (
      <div
        key={`panel:${p.key}`}
        className={wrapperClass()}
        draggable={canDrag}
        onDragStart={canDrag ? onItemDragStart(p.key) : undefined}
        onDragOver={canDrag ? onItemDragOver(p.key) : undefined}
        onDrop={canDrag ? onItemDrop(p.key) : undefined}
        onDragEnd={canDrag ? onItemDragEnd : undefined}
      >
        {canDrag && indicator(p.key, "before")}
        <button
          data-sidebar-panel={p.key}
          onClick={() => handlePanelClick(p.key)}
          className={btnClass(active, isDragged)}
          title={p.label}
        >
          {p.icon}
          {mobile && <span>{p.label}</span>}
        </button>
        {canDrag && indicator(p.key, "after")}
      </div>
    );
  });

  const unavailableButtons = unavailableOrdered.map((key) => {
    const p = panelByKey.get(key);
    if (!p) return null;
    const title = unavailableTitles?.[key] ?? `${p.label} — not part of the demo`;
    const base = mobile
      ? "w-full h-9 flex items-center gap-3 px-3 rounded text-sm text-sol-base01/40 cursor-not-allowed"
      : "w-8 h-8 flex items-center justify-center rounded text-sol-base01/40 cursor-not-allowed";
    return (
      <div key={`unavailable:${p.key}`} className={wrapperClass()}>
        <button
          type="button"
          data-sidebar-panel={p.key}
          data-unavailable={p.label}
          disabled={!onUnavailableSelect}
          onClick={() => onUnavailableSelect?.(p.key)}
          className={base}
          title={title}
          aria-disabled="true"
        >
          {p.icon}
          {mobile && <span>{p.label}</span>}
        </button>
      </div>
    );
  });

  return (
    <div className={mobile ? "flex shrink-0 bg-sol-base03 flex-col items-start p-3 gap-1 w-full h-full" : "hidden md:flex shrink-0 w-10 bg-sol-base03 border-r border-sol-base02 flex-col items-center pt-2"}>
      <div className={mobile ? "flex-1 flex flex-col items-start gap-1 w-full min-h-0 overflow-y-auto" : "flex-1 flex flex-col items-center gap-1 w-full min-h-0 overflow-y-auto pb-1"}>
        {panelButtons}
        {unavailableButtons.length > 0 && (
          <>
            <div className={mobile ? "w-full h-px bg-sol-base02 my-1" : "w-5 h-px bg-sol-base02 my-1"} data-unavailable-divider />
            {unavailableButtons}
          </>
        )}
      </div>
      {/* Bottom: GitHub + Auth */}
      <a
        href="https://github.com/luohy15/y-agent"
        target="_blank"
        rel="noopener noreferrer"
        className={mobile
          ? "mt-auto w-full h-9 flex items-center gap-3 px-3 rounded text-sm text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"
          : "mt-auto w-8 h-8 flex items-center justify-center rounded text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02 shrink-0"
        }
        title="GitHub"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/></svg>
        {mobile && <span>GitHub</span>}
      </a>
      {isLoggedIn && !forceSignInFooter ? (
        <UserMenu email={email ?? null} isLoggedIn={isLoggedIn} mobile={!!mobile} onLogout={() => onLogout?.()} />
      ) : mobile ? (
        forceSignInFooter ? (
          <a
            href="/"
            className="w-full h-9 flex items-center gap-3 px-3 rounded text-sm text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"
            title="Sign in"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" /><polyline points="10 17 15 12 10 7" /><line x1="15" y1="12" x2="3" y2="12" />
            </svg>
            <span>Sign in</span>
          </a>
        ) : (
          <div ref={signinRef} className="px-3 py-1" />
        )
      ) : forceSignInFooter ? (
        <a
          href="/"
          className="w-8 h-8 mb-2 flex items-center justify-center rounded cursor-pointer text-sol-base01 hover:text-sol-base1 hover:bg-sol-base02"
          title="Sign in"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" /><polyline points="10 17 15 12 10 7" /><line x1="15" y1="12" x2="3" y2="12" />
          </svg>
        </a>
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
      {!forceSignInFooter && <SyncStatusPill variant={pill} status={pref.status} />}
    </div>
  );
}

function SyncStatusPill({ variant, status }: { variant: "error" | "offline" | "success" | null; status: SyncStatus }) {
  if (!variant) return null;
  const text =
    variant === "error" ? (status === "syncing" ? "Retrying…" : "Sync failed")
    : variant === "offline" ? "Offline — will retry"
    : "Synced";
  const cls =
    variant === "error" ? "bg-sol-red/15 border-sol-red/30 text-sol-red"
    : variant === "offline" ? "bg-sol-yellow/15 border-sol-yellow/30 text-sol-yellow"
    : "bg-sol-green/15 border-sol-green/30 text-sol-green";
  return (
    <div
      role="status"
      className={`fixed bottom-3 left-3 z-50 px-2.5 py-1 rounded-full border text-xs shadow-float pointer-events-none ${cls}`}
    >
      {text}
    </div>
  );
}
