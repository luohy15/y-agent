// Host ordinary-file workspace helpers (todo 3084 H1/H3/H4).
// Pure functions so restore, open/close/remap, and persistence stay unit-testable
// without mounting App.

import { isOrdinaryFilePath } from "./fileHost";

/** Side table of ordinary-file descriptors keyed by opaque tab id. */
export const HOST_FILE_DESCRIPTORS_KEY = "host.fileDescriptors.v1";

export const FILE_AGGREGATE_TAB = "ui:file";

export interface OrdinaryFileTab {
  id: string;
  path: string;
  vmName: string | null;
  workDir: string | null;
}

export interface HostWorkspaceSnapshot {
  openTabs: string[];
  active: string | null;
  preview: string | null;
  files: Record<string, OrdinaryFileTab>;
}

export interface FileWorkspacePayload {
  version: 1;
  openTabs: string[];
  active: string | null;
  preview: string | null;
  files: OrdinaryFileTab[];
}

export interface FileWorkspaceReconciliation {
  snapshot: HostWorkspaceSnapshot;
  source: "server" | "local";
  shouldPersist: boolean;
}

export interface FocusRequest {
  line: number;
  nonce: number;
}

export function fileTabId(path: string, vmName: string | null, workDir: string | null): string {
  return JSON.stringify([vmName, workDir, path]);
}

export function makeFileTab(path: string, vmName: string | null, workDir: string | null): OrdinaryFileTab {
  const normalized = path.replace(/^\.\//, "");
  return { id: fileTabId(normalized, vmName, workDir), path: normalized, vmName, workDir };
}

export function isOrdinaryFileTabKey(key: string, files: Record<string, OrdinaryFileTab>): boolean {
  return !!files[key];
}

export function ordinaryFileTabFromUnknown(value: unknown): OrdinaryFileTab | null {
  if (typeof value === "string") {
    const path = value.replace(/^\.\//, "");
    return isOrdinaryFilePath(path) ? makeFileTab(path, null, null) : null;
  }
  if (!value || typeof value !== "object") return null;
  const raw = value as Partial<OrdinaryFileTab>;
  if (typeof raw.path !== "string" || !isOrdinaryFilePath(raw.path.replace(/^\.\//, ""))) return null;
  return makeFileTab(
    raw.path,
    typeof raw.vmName === "string" ? raw.vmName : null,
    typeof raw.workDir === "string" ? raw.workDir : null,
  );
}

export function filesFromTabs(tabs: OrdinaryFileTab[]): Record<string, OrdinaryFileTab> {
  return Object.fromEntries(tabs.map((tab) => [tab.id, tab]));
}

export function serializeFileWorkspace(
  snapshot: HostWorkspaceSnapshot,
  isHostSpecialTab?: (path: string) => boolean,
  isPersistable?: (path: string) => boolean,
): FileWorkspacePayload {
  const normalized = isHostSpecialTab && isPersistable
    ? restoreHostWorkspace(
      snapshot.openTabs,
      snapshot.active,
      snapshot.preview,
      snapshot.files,
      isHostSpecialTab,
      isPersistable,
    )
    : snapshot;
  return {
    version: 1,
    openTabs: normalized.openTabs,
    active: normalized.active,
    preview: normalized.preview,
    files: Object.values(normalized.files),
  };
}

/** Parse a backend workspace document through the same policy as local restore. */
export function parseFileWorkspace(
  value: unknown,
  isHostSpecialTab: (path: string) => boolean,
  isPersistable: (path: string) => boolean,
): HostWorkspaceSnapshot | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Partial<FileWorkspacePayload>;
  if (raw.version !== 1 || !Array.isArray(raw.openTabs) || !Array.isArray(raw.files)) return null;
  if (!raw.openTabs.every((key) => typeof key === "string")) return null;
  if (raw.active !== null && typeof raw.active !== "string") return null;
  if (raw.preview !== null && typeof raw.preview !== "string") return null;
  const tabs = raw.files.map(ordinaryFileTabFromUnknown);
  if (tabs.some((tab) => !tab)) return null;
  const files = filesFromTabs(tabs as OrdinaryFileTab[]);
  return restoreHostWorkspace(raw.openTabs, raw.active ?? null, raw.preview ?? null, files, isHostSpecialTab, isPersistable);
}

/** Choose a valid server snapshot unless a local action raced the initial GET. */
export function reconcileFileWorkspace(
  local: HostWorkspaceSnapshot,
  serverValue: unknown,
  userTouched: boolean,
  isHostSpecialTab: (path: string) => boolean,
  isPersistable: (path: string) => boolean,
): FileWorkspaceReconciliation {
  const server = parseFileWorkspace(serverValue, isHostSpecialTab, isPersistable);
  if (server && !userTouched) return { snapshot: server, source: "server", shouldPersist: false };
  return { snapshot: local, source: "local", shouldPersist: true };
}

export function readStoredDescriptors(storage: Pick<Storage, "getItem">): Record<string, OrdinaryFileTab> {
  try {
    const raw = storage.getItem(HOST_FILE_DESCRIPTORS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed) && (!parsed || typeof parsed !== "object")) return {};
    const values = Array.isArray(parsed) ? parsed : Object.values(parsed as Record<string, unknown>);
    const files: Record<string, OrdinaryFileTab> = {};
    for (const value of values) {
      const tab = ordinaryFileTabFromUnknown(value);
      if (tab) files[tab.id] = tab;
    }
    return files;
  } catch {
    return {};
  }
}

export function restoreHostWorkspace(
  openTabsRaw: string[],
  activeRaw: string | null,
  previewRaw: string | null,
  files: Record<string, OrdinaryFileTab>,
  isHostSpecialTab: (path: string) => boolean,
  isPersistable: (path: string) => boolean,
): HostWorkspaceSnapshot {
  const openTabs = openTabsRaw
    .filter((key) => key && key !== FILE_AGGREGATE_TAB)
    .filter((key) => isPersistable(key) || isOrdinaryFileTabKey(key, files))
    .filter((key) => isHostSpecialTab(key) || isOrdinaryFileTabKey(key, files))
    .filter((key, index, all) => all.indexOf(key) === index)
    .filter((key) => isHostSpecialTab(key) || !!files[key]);
  const keptFiles = filesFromTabs(openTabs.map((key) => files[key]).filter(Boolean) as OrdinaryFileTab[]);
  const active = activeRaw && openTabs.includes(activeRaw) ? activeRaw : openTabs[0] ?? null;
  const preview = previewRaw && openTabs.includes(previewRaw) && keptFiles[previewRaw] ? previewRaw : null;
  return { openTabs, active, preview, files: keptFiles };
}

/** Persist host workspace. Returns false on storage failure. */
export function persistHostWorkspace(
  storage: Pick<Storage, "setItem" | "removeItem">,
  snapshot: HostWorkspaceSnapshot,
): boolean {
  try {
    storage.setItem("openFiles", JSON.stringify(snapshot.openTabs));
    if (snapshot.active) storage.setItem("activeFile", snapshot.active);
    else storage.removeItem("activeFile");
    if (snapshot.preview) storage.setItem("previewFile", snapshot.preview);
    else storage.removeItem("previewFile");
    storage.setItem(HOST_FILE_DESCRIPTORS_KEY, JSON.stringify(Object.values(snapshot.files)));
    return true;
  } catch {
    return false;
  }
}

export function openOrdinaryWorkspaceTab(
  state: HostWorkspaceSnapshot,
  tab: OrdinaryFileTab,
  preview: boolean,
): HostWorkspaceSnapshot {
  const exists = state.openTabs.includes(tab.id);
  let openTabs = state.openTabs;
  if (!exists) {
    if (preview && state.preview && state.openTabs.includes(state.preview)) {
      openTabs = state.openTabs.map((key) => (key === state.preview ? tab.id : key));
    } else {
      openTabs = [...state.openTabs, tab.id];
    }
  }
  const files = { ...state.files, [tab.id]: tab };
  // Drop descriptor for a replaced preview tab.
  if (preview && state.preview && state.preview !== tab.id && !openTabs.includes(state.preview)) {
    const nextFiles = { ...files };
    delete nextFiles[state.preview];
    return {
      openTabs,
      active: tab.id,
      preview: tab.id,
      files: nextFiles,
    };
  }
  return {
    openTabs,
    active: tab.id,
    preview: preview ? tab.id : state.preview === tab.id ? null : state.preview,
    files,
  };
}

/** Per-tab back/forward stacks (todo 3288). Session-scoped, kept in App state
 * rather than the persisted workspace payload. */
export interface TabHistory {
  back: OrdinaryFileTab[];
  forward: OrdinaryFileTab[];
}

export type TabHistoryMap = Record<string, TabHistory>;

/** Cap on entries per back/forward stack; oldest entries drop first. */
export const TAB_HISTORY_DEPTH_CAP = 32;

/**
 * `openOrdinaryWorkspaceTab` plus history bookkeeping: when the open replaces
 * the preview tab in place, the replaced tab's history transfers to the new
 * tab id with the replaced tab pushed onto `back` and `forward` cleared (a
 * normal navigation, not a history step). A non-replacing open (already open
 * elsewhere, or the preview tab survives) records nothing. The replaced
 * preview must also be the active tab: a link click always navigates the
 * currently active tab, so a preview that is open but not active is a
 * displaced background tab, not the click's source, and must not seed the
 * new tab's back history.
 */
export function openOrdinaryWorkspaceTabWithHistory(
  state: HostWorkspaceSnapshot,
  history: TabHistoryMap,
  tab: OrdinaryFileTab,
  preview: boolean,
): { snapshot: HostWorkspaceSnapshot; history: TabHistoryMap } {
  const replacedId = !state.openTabs.includes(tab.id)
    && preview
    && state.preview
    && state.active === state.preview
    && state.openTabs.includes(state.preview)
    ? state.preview
    : null;
  const snapshot = openOrdinaryWorkspaceTab(state, tab, preview);
  const replacedTab = replacedId ? state.files[replacedId] : null;
  if (!replacedId || !replacedTab) return { snapshot, history };
  const prior = history[replacedId] ?? { back: [], forward: [] };
  const nextHistory = { ...history };
  delete nextHistory[replacedId];
  nextHistory[tab.id] = {
    back: [...prior.back, replacedTab].slice(-TAB_HISTORY_DEPTH_CAP),
    forward: [],
  };
  return { snapshot, history: nextHistory };
}

/** Swap the active tab's id in place, keeping its strip position and its
 * preview/pinned status. Used by `stepTabHistory` to step back/forward
 * without disturbing tab order. No-op if the target id is already open in a
 * different slot (avoids a duplicate strip key). */
export function replaceOrdinaryTabInPlace(
  state: HostWorkspaceSnapshot,
  tab: OrdinaryFileTab,
): HostWorkspaceSnapshot {
  const activeId = state.active;
  if (!activeId) return state;
  const idx = state.openTabs.indexOf(activeId);
  if (idx < 0) return state;
  if (tab.id !== activeId && state.openTabs.includes(tab.id)) return state;
  const openTabs = state.openTabs.map((key) => (key === activeId ? tab.id : key));
  const files = { ...state.files };
  if (activeId !== tab.id) delete files[activeId];
  files[tab.id] = tab;
  return {
    openTabs,
    active: tab.id,
    preview: state.preview === activeId ? tab.id : state.preview,
    files,
  };
}

/**
 * Step the active tab's history one entry back or forward, replacing it in
 * place. Returns null when there is no active ordinary tab, its stack in
 * that direction is empty, or the target id has since collided with a tab
 * already open elsewhere (`replaceOrdinaryTabInPlace` would no-op) — in the
 * collision case the stack and history map are left untouched rather than
 * being partially consumed.
 */
export function stepTabHistory(
  state: HostWorkspaceSnapshot,
  history: TabHistoryMap,
  direction: "back" | "forward",
): { snapshot: HostWorkspaceSnapshot; history: TabHistoryMap } | null {
  const activeId = state.active;
  if (!activeId) return null;
  const current = state.files[activeId];
  if (!current) return null;
  const entry = history[activeId] ?? { back: [], forward: [] };
  const sourceStack = direction === "back" ? entry.back : entry.forward;
  if (sourceStack.length === 0) return null;
  const target = sourceStack[sourceStack.length - 1];
  const snapshot = replaceOrdinaryTabInPlace(state, target);
  if (snapshot === state) return null;
  const remainingSource = sourceStack.slice(0, -1);
  const destStack = direction === "back" ? entry.forward : entry.back;
  const nextDestStack = [...destStack, current].slice(-TAB_HISTORY_DEPTH_CAP);
  const nextHistory = { ...history };
  delete nextHistory[activeId];
  nextHistory[target.id] = direction === "back"
    ? { back: remainingSource, forward: nextDestStack }
    : { back: nextDestStack, forward: remainingSource };
  return { snapshot, history: nextHistory };
}

/** Drop history dying with a closed/removed tab. */
export function dropTabHistory(history: TabHistoryMap, tabIds: string[]): TabHistoryMap {
  if (tabIds.length === 0 || tabIds.every((id) => !(id in history))) return history;
  const next = { ...history };
  for (const id of tabIds) delete next[id];
  return next;
}

/** Remap history keys through `remapOrdinaryTabs`' idMap. Stack entries (old
 * paths) are left as-is; a stale entry just shows the viewer's normal
 * missing-file view when stepped into. */
export function remapTabHistory(history: TabHistoryMap, idMap: Map<string, string>): TabHistoryMap {
  if (idMap.size === 0) return history;
  let changed = false;
  const next: TabHistoryMap = {};
  for (const [key, entry] of Object.entries(history)) {
    const mapped = idMap.get(key);
    if (mapped && mapped !== key) {
      next[mapped] = entry;
      changed = true;
    } else {
      next[key] = entry;
    }
  }
  return changed ? next : history;
}

export function closeWorkspaceTabKey(state: HostWorkspaceSnapshot, key: string): HostWorkspaceSnapshot {
  const index = state.openTabs.indexOf(key);
  const openTabs = state.openTabs.filter((tab) => tab !== key);
  const files = { ...state.files };
  if (files[key]) delete files[key];
  const active = state.active !== key
    ? state.active
    : (index < 0 ? openTabs[0] : openTabs[Math.min(index, openTabs.length - 1)]) ?? null;
  return {
    openTabs,
    active,
    preview: state.preview === key ? null : state.preview,
    files,
  };
}

function pathMatches(tabPath: string, target: string): boolean {
  return tabPath === target || tabPath.startsWith(`${target}/`);
}

function sameContext(tab: OrdinaryFileTab, vmName: string | null | undefined, workDir: string | null | undefined): boolean {
  // Undefined context means "all contexts" (legacy module event had path only).
  if (vmName === undefined && workDir === undefined) return true;
  const vm = vmName === undefined ? tab.vmName : vmName;
  const dir = workDir === undefined ? tab.workDir : workDir;
  return tab.vmName === (typeof vm === "string" || vm === null ? vm : tab.vmName)
    && tab.workDir === (typeof dir === "string" || dir === null ? dir : tab.workDir);
}

export type RemapOrdinaryTabsResult = HostWorkspaceSnapshot & {
  /** Old tab id -> new tab id for tabs whose path was remapped. */
  idMap: Map<string, string>;
};

/** Remap matching ordinary tabs by path within an optional VM/workDir scope. */
export function remapOrdinaryTabs(
  state: HostWorkspaceSnapshot,
  oldPath: string,
  newPath: string,
  vmName?: string | null,
  workDir?: string | null,
): RemapOrdinaryTabsResult {
  const normOld = oldPath.replace(/^\.\//, "");
  const normNew = newPath.replace(/^\.\//, "");
  const idMap = new Map<string, string>();
  const files: Record<string, OrdinaryFileTab> = {};
  for (const tab of Object.values(state.files)) {
    if (pathMatches(tab.path, normOld) && sameContext(tab, vmName, workDir)) {
      const nextPath = `${normNew}${tab.path.slice(normOld.length)}`;
      const next = makeFileTab(nextPath, tab.vmName, tab.workDir);
      idMap.set(tab.id, next.id);
      // Last write wins on id collision after remap.
      files[next.id] = next;
    } else if (!files[tab.id]) {
      files[tab.id] = tab;
    }
  }
  const finalTabs = state.openTabs
    .map((key) => idMap.get(key) ?? key)
    .filter((key, index, all) => all.indexOf(key) === index)
    .filter((key) => !isLikelyFileTabId(key) || !!files[key]);
  const active = state.active ? idMap.get(state.active) ?? state.active : null;
  const preview = state.preview ? idMap.get(state.preview) ?? state.preview : null;
  return {
    openTabs: finalTabs,
    active: active && finalTabs.includes(active) ? active : finalTabs[0] ?? null,
    preview: preview && finalTabs.includes(preview) && files[preview] ? preview : null,
    files,
    idMap,
  };
}

function isLikelyFileTabId(key: string): boolean {
  // Ordinary host tab ids are JSON.stringify([vm, workDir, path]).
  return key.startsWith("[");
}

/** Close matching ordinary tabs by path within an optional VM/workDir scope. */
export function removeOrdinaryTabs(
  state: HostWorkspaceSnapshot,
  path: string,
  vmName?: string | null,
  workDir?: string | null,
): HostWorkspaceSnapshot {
  const norm = path.replace(/^\.\//, "");
  const drop = new Set(
    Object.values(state.files)
      .filter((tab) => pathMatches(tab.path, norm) && sameContext(tab, vmName, workDir))
      .map((tab) => tab.id),
  );
  let next = state;
  for (const key of state.openTabs) {
    if (drop.has(key)) next = closeWorkspaceTabKey(next, key);
  }
  return next;
}

export function fileDetailContext(
  tab: OrdinaryFileTab,
  active: boolean,
  focus?: FocusRequest,
): {
  tabId: string;
  path: string;
  vmName: string | null;
  workDir: string | null;
  active: boolean;
  focus?: FocusRequest;
} {
  return {
    tabId: tab.id,
    path: tab.path,
    vmName: tab.vmName,
    workDir: tab.workDir,
    active,
    ...(focus ? { focus } : {}),
  };
}

export function fileDirtyPayload(payload: unknown): { tabId: string; dirty: boolean } | undefined {
  if (!payload || typeof payload !== "object") return undefined;
  const { tabId, dirty } = payload as { tabId?: unknown; dirty?: unknown };
  if (typeof tabId !== "string" || typeof dirty !== "boolean") return undefined;
  return { tabId, dirty };
}

export function fileRemapPayload(payload: unknown): {
  oldPath: string;
  newPath: string;
  vmName?: string | null;
  workDir?: string | null;
} | undefined {
  if (!payload || typeof payload !== "object") return undefined;
  const { oldPath, newPath, vmName, workDir } = payload as {
    oldPath?: unknown;
    newPath?: unknown;
    vmName?: unknown;
    workDir?: unknown;
  };
  if (typeof oldPath !== "string" || typeof newPath !== "string") return undefined;
  return {
    oldPath,
    newPath,
    ...(vmName === undefined ? {} : { vmName: typeof vmName === "string" ? vmName : null }),
    ...(workDir === undefined ? {} : { workDir: typeof workDir === "string" ? workDir : null }),
  };
}

export function fileRemovePayload(payload: unknown): {
  path: string;
  vmName?: string | null;
  workDir?: string | null;
} | undefined {
  if (!payload || typeof payload !== "object") return undefined;
  const { path, vmName, workDir } = payload as {
    path?: unknown;
    vmName?: unknown;
    workDir?: unknown;
  };
  if (typeof path !== "string") return undefined;
  return {
    path,
    ...(vmName === undefined ? {} : { vmName: typeof vmName === "string" ? vmName : null }),
    ...(workDir === undefined ? {} : { workDir: typeof workDir === "string" ? workDir : null }),
  };
}
