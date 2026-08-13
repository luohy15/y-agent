// Host ordinary-file workspace helpers (todo 3084 H1/H3/H4).
// Pure functions so migration, open/close/remap, and persistence stay unit-testable
// without mounting App. Module-owned file.workspace.v2 is read once as the
// migration source and left in place for rollback; the host never writes it.

import { isOrdinaryFilePath } from "./fileHost";

/** Module workspace key kept as rollback data through the 3084 rollout. */
export const FILE_WORKSPACE_STORAGE_KEY = "file.workspace.v2";
/** One-way host migration marker: set only after the host workspace write succeeds. */
export const HOST_FILE_TABS_MIGRATION_KEY = "host.fileTabs.v1.migrated";
/**
 * Collapsed aggregate presentation while the active file module is non-contextual
 * after a prior migration. Survives reload; cleared when contextual mode remounts
 * ordinary tabs. Distinct from the migration marker so remigrate remains possible.
 */
export const HOST_FILE_TABS_COLLAPSED_KEY = "host.fileTabs.v1.collapsed";
/** Side table of ordinary-file descriptors keyed by opaque tab id. */
export const HOST_FILE_DESCRIPTORS_KEY = "host.fileDescriptors.v1";

export const FILE_AGGREGATE_TAB = "ui:file";

export interface OrdinaryFileTab {
  id: string;
  path: string;
  vmName: string | null;
  workDir: string | null;
}

export interface ModuleWorkspaceState {
  tabs: OrdinaryFileTab[];
  active: string | null;
  preview: string | null;
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

/** Sanitize the module's file.workspace.v2 payload; null means corrupt/unusable. */
export function sanitizeModuleWorkspace(value: unknown): ModuleWorkspaceState | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Partial<ModuleWorkspaceState>;
  if (!Array.isArray(raw.tabs)) return null;
  const tabs = raw.tabs
    .map(ordinaryFileTabFromUnknown)
    .filter((tab): tab is OrdinaryFileTab => !!tab)
    .filter((tab, index, all) => all.findIndex((candidate) => candidate.id === tab.id) === index);
  const active = typeof raw.active === "string" && tabs.some((tab) => tab.id === raw.active)
    ? raw.active
    : tabs[0]?.id ?? null;
  const preview = typeof raw.preview === "string" && tabs.some((tab) => tab.id === raw.preview)
    ? raw.preview
    : null;
  return { tabs, active, preview };
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

/**
 * Merge module workspace tabs into the host list at the former `ui:file` slot.
 * Pure: does not touch storage. Caller writes the result and only then sets the
 * migration marker (a failed write must leave migration retryable).
 */
export function mergeModuleWorkspaceIntoHost(
  hostOpenTabs: string[],
  hostActive: string | null,
  hostPreview: string | null,
  hostFiles: Record<string, OrdinaryFileTab>,
  moduleState: ModuleWorkspaceState | null,
): HostWorkspaceSnapshot {
  const aggregateIdx = hostOpenTabs.indexOf(FILE_AGGREGATE_TAB);
  const withoutAggregate = hostOpenTabs.filter((key) => key !== FILE_AGGREGATE_TAB);
  const moduleTabs = moduleState?.tabs ?? [];
  const moduleFiles = filesFromTabs(moduleTabs);
  // Host descriptors win on id collision (already-restored ordinary tabs).
  const files: Record<string, OrdinaryFileTab> = { ...moduleFiles, ...hostFiles };
  const moduleIds = moduleTabs.map((tab) => tab.id).filter((id, index, all) => all.indexOf(id) === index);
  // Non-module host keys: specials + ordinary tabs the host already owns.
  const hostKept = withoutAggregate.filter((key) => !moduleFiles[key]);

  let openTabs: string[];
  if (aggregateIdx >= 0) {
    const before: string[] = [];
    const after: string[] = [];
    for (const key of hostKept) {
      if (hostOpenTabs.indexOf(key) < aggregateIdx) before.push(key);
      else after.push(key);
    }
    openTabs = [...before, ...moduleIds, ...after].filter((key, index, all) => all.indexOf(key) === index);
  } else {
    openTabs = [...hostKept, ...moduleIds].filter((key, index, all) => all.indexOf(key) === index);
  }

  openTabs = openTabs.filter((key) => !isLikelyFileTabId(key) || !!files[key]);
  const keptFiles = filesFromTabs(openTabs.map((key) => files[key]).filter(Boolean) as OrdinaryFileTab[]);

  let active: string | null;
  if (hostActive === FILE_AGGREGATE_TAB) {
    active = moduleState?.active && openTabs.includes(moduleState.active)
      ? moduleState.active
      : openTabs[0] ?? null;
  } else if (hostActive && openTabs.includes(hostActive)) {
    active = hostActive;
  } else {
    active = openTabs[0] ?? null;
  }

  let preview: string | null = null;
  if (moduleState?.preview && openTabs.includes(moduleState.preview)) {
    preview = moduleState.preview;
  } else if (
    hostPreview
    && hostPreview !== FILE_AGGREGATE_TAB
    && openTabs.includes(hostPreview)
    && keptFiles[hostPreview]
  ) {
    preview = hostPreview;
  }

  return { openTabs, active, preview, files: keptFiles };
}

export function readModuleWorkspace(storage: Pick<Storage, "getItem">): ModuleWorkspaceState | null {
  const raw = storage.getItem(FILE_WORKSPACE_STORAGE_KEY);
  if (raw === null) return null;
  try {
    return sanitizeModuleWorkspace(JSON.parse(raw));
  } catch {
    return null;
  }
}

/**
 * Initial host restore before the active file module version is known.
 * - collapsed after migration: keep specials including ui:file, no ordinary tabs
 * - migrated contextual: restore ordinary descriptors, strip ui:file
 * - pre-cutover aggregate: keep specials including ui:file, no ordinary tabs
 */
export function restoreHostWorkspaceWithoutMigration(
  hostOpenTabs: string[],
  hostActive: string | null,
  hostPreview: string | null,
  hostFiles: Record<string, OrdinaryFileTab>,
  isHostSpecialTab: (path: string) => boolean,
  isPersistable: (path: string) => boolean,
  migrationDone: boolean,
  collapsed = false,
): HostWorkspaceSnapshot {
  if (migrationDone && !collapsed) {
    return restoreHostWorkspace(hostOpenTabs, hostActive, hostPreview, hostFiles, isHostSpecialTab, isPersistable);
  }
  // Pre-cutover or collapsed aggregate: keep specials (including ui:file).
  // Do not invent ordinary tabs; descriptors stay in storage for remigrate.
  const openTabs = hostOpenTabs
    .filter((key) => key && isHostSpecialTab(key))
    .filter((key) => isPersistable(key))
    .filter((key, index, all) => all.indexOf(key) === index);
  const active = hostActive && openTabs.includes(hostActive) ? hostActive : openTabs[0] ?? null;
  const preview = hostPreview && openTabs.includes(hostPreview) ? hostPreview : null;
  return { openTabs, active, preview, files: {} };
}

/** Remigrate ordinary tabs after a collapsed aggregate rollback. Prefer retained
 * host descriptors, then file.workspace.v2, merging at the ui:file slot. */
export function remigrateFromRetainedSources(
  storage: Pick<Storage, "getItem">,
  hostOpenTabs: string[],
  hostActive: string | null,
  hostPreview: string | null,
  hostFiles: Record<string, OrdinaryFileTab>,
  isHostSpecialTab: (path: string) => boolean,
  isPersistable: (path: string) => boolean,
): HostWorkspaceSnapshot {
  const retained = Object.keys(hostFiles).length > 0 ? hostFiles : readStoredDescriptors(storage);
  const moduleState = readModuleWorkspace(storage);
  // Prefer retained host descriptors; fill gaps from module workspace.
  const seedFiles = retained;
  const seedTabs = Object.keys(seedFiles).length > 0
    ? null
    : moduleState;
  // When host descriptors exist, synthesize a module-like ordered list from them
  // only if openTabs no longer carries ordinary ids (collapsed).
  const syntheticModule = seedTabs ?? {
    tabs: Object.values(seedFiles),
    active: moduleState?.active && seedFiles[moduleState.active] ? moduleState.active : Object.values(seedFiles)[0]?.id ?? null,
    preview: moduleState?.preview && seedFiles[moduleState.preview] ? moduleState.preview : null,
  };
  const merged = mergeModuleWorkspaceIntoHost(
    hostOpenTabs,
    hostActive,
    hostPreview,
    seedFiles,
    // Always pass a workspace so aggregate slot is replaced even when only host
    // descriptors remain after collapse cleared live fileTabs.
    syntheticModule.tabs.length > 0 ? syntheticModule : moduleState,
  );
  return restoreHostWorkspace(
    merged.openTabs,
    merged.active,
    merged.preview,
    merged.files,
    isHostSpecialTab,
    isPersistable,
  );
}

/**
 * First contextual-file start migration. Returns the workspace to use and
 * whether the caller should persist + mark migration. Corrupt/missing module
 * state still removes `ui:file` and leaves specials alone. Must only be called
 * when the active file module is contextual (host contract v8+).
 */
export function migrateHostWorkspaceOnLoad(
  storage: Pick<Storage, "getItem">,
  hostOpenTabs: string[],
  hostActive: string | null,
  hostPreview: string | null,
  hostFiles: Record<string, OrdinaryFileTab>,
  isHostSpecialTab: (path: string) => boolean,
  isPersistable: (path: string) => boolean,
): { snapshot: HostWorkspaceSnapshot; shouldPersistMigration: boolean } {
  if (storage.getItem(HOST_FILE_TABS_MIGRATION_KEY) === "true") {
    return {
      snapshot: restoreHostWorkspace(hostOpenTabs, hostActive, hostPreview, hostFiles, isHostSpecialTab, isPersistable),
      shouldPersistMigration: false,
    };
  }
  const moduleState = readModuleWorkspace(storage);
  const merged = mergeModuleWorkspaceIntoHost(hostOpenTabs, hostActive, hostPreview, hostFiles, moduleState);
  // Also drop any aggregate residue and non-persistable artifacts.
  const cleaned = restoreHostWorkspace(
    merged.openTabs,
    merged.active,
    merged.preview,
    merged.files,
    isHostSpecialTab,
    isPersistable,
  );
  return { snapshot: cleaned, shouldPersistMigration: true };
}

/** Collapse ordinary host descriptors back to a single aggregate `ui:file` tab
 * for staged rollout while the active file module still ignores detailContext. */
export function collapseOrdinaryTabsToAggregate(state: HostWorkspaceSnapshot): HostWorkspaceSnapshot {
  const specials = state.openTabs.filter((key) => !state.files[key] && key !== FILE_AGGREGATE_TAB);
  const hadOrdinary = state.openTabs.some((key) => !!state.files[key]);
  const openTabs = hadOrdinary || state.openTabs.includes(FILE_AGGREGATE_TAB)
    ? [...specials, FILE_AGGREGATE_TAB].filter((key, index, all) => all.indexOf(key) === index)
    : specials;
  const activeWasOrdinary = !!(state.active && state.files[state.active]);
  const active = activeWasOrdinary || state.active === FILE_AGGREGATE_TAB
    ? (openTabs.includes(FILE_AGGREGATE_TAB) ? FILE_AGGREGATE_TAB : openTabs[0] ?? null)
    : state.active && openTabs.includes(state.active)
      ? state.active
      : openTabs[0] ?? null;
  return { openTabs, active, preview: null, files: {} };
}

/** Persist host workspace. Returns false on storage failure (migration stays retryable). */
export function persistHostWorkspace(
  storage: Pick<Storage, "setItem" | "removeItem">,
  snapshot: HostWorkspaceSnapshot,
  markMigrated: boolean,
): boolean {
  try {
    storage.setItem("openFiles", JSON.stringify(snapshot.openTabs));
    if (snapshot.active) storage.setItem("activeFile", snapshot.active);
    else storage.removeItem("activeFile");
    if (snapshot.preview) storage.setItem("previewFile", snapshot.preview);
    else storage.removeItem("previewFile");
    storage.setItem(HOST_FILE_DESCRIPTORS_KEY, JSON.stringify(Object.values(snapshot.files)));
    if (markMigrated) storage.setItem(HOST_FILE_TABS_MIGRATION_KEY, "true");
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

/** Remap matching ordinary tabs by path within an optional VM/workDir scope. */
export function remapOrdinaryTabs(
  state: HostWorkspaceSnapshot,
  oldPath: string,
  newPath: string,
  vmName?: string | null,
  workDir?: string | null,
): HostWorkspaceSnapshot {
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
